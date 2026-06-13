"""CPU ラスタ、Image 同期、GPU テクスチャ、ブラシ描画。"""

from __future__ import annotations

import time

import bpy
import gpu
import numpy as np
from mathutils import Vector

from .properties import get_session

_IMAGE_PREFIX = "BlenerPaint_"
_GPU_FPS = 30.0
_LAYER_CACHE: dict[str, "PaintPixelLayer"] = {}
_STROKE_STATE = None


# --- Pixel buffer ---


class PixelBuffer:
    # RGBA8 のピクセル配列と更新領域(dirty rect)を管理する。
    __slots__ = ("width", "height", "pixels", "_dirty", "_dirty_rect")

    def __init__(self, width: int, height: int, *, clear: bool = True):
        # 指定サイズのバッファを作成し、必要なら初期色で埋める。
        self.width = width
        self.height = height
        self.pixels = np.zeros((height, width, 4), dtype=np.uint8)
        if clear:
            self.pixels[..., 3] = 255
        self._dirty = False
        self._dirty_rect = None
        if clear:
            self.mark_dirty_full()

    def clear(self, rgba=(0, 0, 0, 255)) -> None:
        # バッファ全体を指定色でクリアする。
        self.pixels[:] = rgba
        self.mark_dirty_full()

    def mark_dirty_full(self) -> None:
        # 全画面を更新対象としてマークする。
        self._dirty = True
        self._dirty_rect = (0, 0, self.width - 1, self.height - 1)

    def mark_dirty_rect(self, x0, y0, x1, y1) -> None:
        # 指定矩形をクランプして更新対象にマージする。
        x0 = max(0, min(x0, self.width - 1))
        x1 = max(0, min(x1, self.width - 1))
        y0 = max(0, min(y0, self.height - 1))
        y1 = max(0, min(y1, self.height - 1))
        if x0 > x1 or y0 > y1:
            return
        self._dirty = True
        if self._dirty_rect is None:
            self._dirty_rect = (x0, y0, x1, y1)
        else:
            ox0, oy0, ox1, oy1 = self._dirty_rect
            self._dirty_rect = (min(ox0, x0), min(oy0, y0), max(ox1, x1), max(oy1, y1))

    def has_dirty(self) -> bool:
        # 未反映の更新があるかを返す。
        return self._dirty

    def consume_dirty_rect(self):
        # 更新矩形を取得し、dirty 状態をクリアする。
        if not self._dirty:
            return None
        rect = self._dirty_rect
        self._dirty = False
        self._dirty_rect = None
        return rect

    def peek_dirty_rect(self):
        # 現在の更新矩形を状態変更せず返す。
        return self._dirty_rect

    @classmethod
    def from_image_pixels(cls, width, height, flat_pixels):
        # Blender Image の float 配列から RGBA8 バッファを復元する。
        buf = cls(width, height, clear=False)
        arr = np.array(flat_pixels, dtype=np.float32).reshape((height, width, 4))
        buf.pixels[:] = (np.clip(np.flipud(arr), 0.0, 1.0) * 255.0).astype(np.uint8)
        buf.mark_dirty_full()
        return buf


# --- Raster brush ---


def uv_to_pixel(uv: Vector, width: int, height: int) -> tuple[int, int]:
    # UV(0..1) を画像ピクセル座標へ変換する。
    x = int(round(uv.x * (width - 1)))
    y = int(round((1.0 - uv.y) * (height - 1)))
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))


def _blend_src_over(dst: np.ndarray, coverage: np.ndarray, src: np.ndarray) -> None:
    # coverage(0..1) を掛けた src を Source-Over 合成する。
    cov = np.clip(coverage.astype(np.float32), 0.0, 1.0)
    if not np.any(cov > 0.0):
        return
    src_a = float(src[3]) / 255.0
    if src_a <= 0.0:
        return
    sa = cov * src_a
    active = sa > 0.0
    if not np.any(active):
        return
    dst_f = dst[active].astype(np.float32)
    sa_f = sa[active]
    da = dst_f[:, 3] / 255.0
    out_a = sa_f + da * (1.0 - sa_f)
    out_a_safe = np.maximum(out_a, 1e-6)
    out = np.empty_like(dst_f, dtype=np.float32)
    for c in range(3):
        out[:, c] = (src[c] * sa_f + dst_f[:, c] * da * (1.0 - sa_f)) / out_a_safe
    out[:, 3] = out_a * 255.0
    dst[active] = np.clip(np.round(out), 0, 255).astype(np.uint8)


def _blend_src_over_base(base: np.ndarray, dst: np.ndarray, coverage: np.ndarray, src: np.ndarray) -> None:
    # base を背景として、coverage(0..1)付き src を再合成して dst に反映する。
    cov = np.clip(coverage.astype(np.float32), 0.0, 1.0)
    src_a = float(src[3]) / 255.0
    if src_a <= 0.0:
        dst[:] = base
        return
    sa = cov * src_a
    active = sa > 0.0
    dst[:] = base
    if not np.any(active):
        return
    base_f = base[active].astype(np.float32)
    sa_f = sa[active]
    da = base_f[:, 3] / 255.0
    out_a = sa_f + da * (1.0 - sa_f)
    out_a_safe = np.maximum(out_a, 1e-6)
    out = np.empty_like(base_f, dtype=np.float32)
    for c in range(3):
        out[:, c] = (src[c] * sa_f + base_f[:, c] * da * (1.0 - sa_f)) / out_a_safe
    out[:, 3] = out_a * 255.0
    dst[active] = np.clip(np.round(out), 0, 255).astype(np.uint8)


def _hardness_coverage(dist_sq: np.ndarray, radius: int, hardness: float) -> np.ndarray:
    # 半径と hardness から距離ベースの被覆率(0..1)を返す。
    r = max(1, int(radius))
    h = max(0.0, min(1.0, float(hardness)))
    dist = np.sqrt(dist_sq.astype(np.float32))
    coverage = np.zeros_like(dist, dtype=np.float32)
    inside = dist <= float(r)
    if not np.any(inside):
        return coverage
    if h >= 1.0:
        coverage[inside] = 1.0
        return coverage
    inner = h * float(r)
    hard = inside & (dist <= inner)
    coverage[hard] = 1.0
    soft = inside & ~hard
    if np.any(soft):
        soft_width = max(float(r) - inner, 1e-6)
        coverage[soft] = 1.0 - ((dist[soft] - inner) / soft_width)
    return np.clip(coverage, 0.0, 1.0)


def _stamp_disc(buffer: PixelBuffer, cx, cy, radius, color_rgba, hardness=1.0) -> None:
    # 円形スタンプを 1 回押して描画する。
    r = max(0, radius)
    x0, x1 = max(0, cx - r), min(buffer.width - 1, cx + r)
    y0, y1 = max(0, cy - r), min(buffer.height - 1, cy + r)
    sub = buffer.pixels[y0 : y1 + 1, x0 : x1 + 1]
    yy, xx = np.ogrid[y0 : y1 + 1, x0 : x1 + 1]
    dist_sq = (xx - cx) ** 2 + (yy - cy) ** 2
    coverage = _hardness_coverage(dist_sq, r, hardness)
    _blend_src_over(sub, coverage, np.array(color_rgba, dtype=np.uint8))
    buffer.mark_dirty_rect(x0, y0, x1, y1)


def _paint_segment(buffer, x0, y0, x1, y1, color_rgba, radius, hardness=1.0) -> None:
    # 線分と半径からブラシ軌跡をラスター化して描画する。
    r = max(0, radius)
    x_min = max(0, min(x0, x1) - r)
    x_max = min(buffer.width - 1, max(x0, x1) + r)
    y_min = max(0, min(y0, y1) - r)
    y_max = min(buffer.height - 1, max(y0, y1) + r)
    ax, ay, bx, by = float(x0), float(y0), float(x1), float(y1)
    abx, aby = bx - ax, by - ay
    ab_len_sq = abx * abx + aby * aby
    yy, xx = np.ogrid[y_min : y_max + 1, x_min : x_max + 1]
    if ab_len_sq < 1e-6:
        dist_sq = (xx - ax) ** 2 + (yy - ay) ** 2
    else:
        t = np.clip(((xx - ax) * abx + (yy - ay) * aby) / ab_len_sq, 0.0, 1.0)
        dist_sq = (xx - (ax + t * abx)) ** 2 + (yy - (ay + t * aby)) ** 2
    sub = buffer.pixels[y_min : y_max + 1, x_min : x_max + 1]
    coverage = _hardness_coverage(dist_sq, r, hardness)
    _blend_src_over(sub, coverage, np.array(color_rgba, dtype=np.uint8))
    buffer.mark_dirty_rect(x_min, y_min, x_max, y_max)


def _segment_coverage(width, height, x0, y0, x1, y1, radius, hardness):
    # 線分の影響範囲矩形と被覆率を返す。
    r = max(0, int(radius))
    x_min = max(0, min(x0, x1) - r)
    x_max = min(width - 1, max(x0, x1) + r)
    y_min = max(0, min(y0, y1) - r)
    y_max = min(height - 1, max(y0, y1) + r)
    ax, ay, bx, by = float(x0), float(y0), float(x1), float(y1)
    abx, aby = bx - ax, by - ay
    ab_len_sq = abx * abx + aby * aby
    yy, xx = np.ogrid[y_min : y_max + 1, x_min : x_max + 1]
    if ab_len_sq < 1e-6:
        dist_sq = (xx - ax) ** 2 + (yy - ay) ** 2
    else:
        t = np.clip(((xx - ax) * abx + (yy - ay) * aby) / ab_len_sq, 0.0, 1.0)
        dist_sq = (xx - (ax + t * abx)) ** 2 + (yy - (ay + t * aby)) ** 2
    coverage = _hardness_coverage(dist_sq, r, hardness)
    return x_min, y_min, x_max, y_max, coverage


class _StrokeState:
    # 同一ストローク内の重なり抑制用に、ベース画像と max マスクを保持する。
    __slots__ = ("layer", "base_pixels", "mask", "src", "radius", "hardness")

    def __init__(self, layer, src, radius, hardness):
        self.layer = layer
        self.base_pixels = layer.buffer.pixels.copy()
        self.mask = np.zeros((layer.buffer.height, layer.buffer.width), dtype=np.float32)
        self.src = src
        self.radius = radius
        self.hardness = hardness


def begin_paint_stroke(context, color_rgba, radius_px, hardness=1.0) -> bool:
    # ストローク開始時に基準バッファとマスクを初期化する。
    global _STROKE_STATE
    layer = get_pixel_layer(context)
    if layer is None:
        _STROKE_STATE = None
        return False
    color = tuple(int(round(max(0.0, min(1.0, c)) * 255.0)) for c in color_rgba[:4])
    if len(color) == 3:
        color = (*color, 255)
    _STROKE_STATE = _StrokeState(
        layer=layer,
        src=np.array(color, dtype=np.uint8),
        radius=max(1, int(radius_px)),
        hardness=max(0.0, min(1.0, float(hardness))),
    )
    return True


def _stroke_paint_pixels(x0, y0, x1, y1):
    # 線分被覆率をストロークマスクへ max 合成し、対象領域のみ再合成する。
    state = _STROKE_STATE
    if state is None:
        return
    h, w = state.layer.buffer.height, state.layer.buffer.width
    x_min, y_min, x_max, y_max, coverage = _segment_coverage(
        w, h, x0, y0, x1, y1, state.radius, state.hardness
    )
    mask_sub = state.mask[y_min : y_max + 1, x_min : x_max + 1]
    np.maximum(mask_sub, coverage, out=mask_sub)
    base_sub = state.base_pixels[y_min : y_max + 1, x_min : x_max + 1]
    dst_sub = state.layer.buffer.pixels[y_min : y_max + 1, x_min : x_max + 1]
    _blend_src_over_base(base_sub, dst_sub, mask_sub, state.src)
    state.layer.buffer.mark_dirty_rect(x_min, y_min, x_max, y_max)
    state.layer.invalidate_gpu()


def paint_stroke_dab(context, uv) -> None:
    # アクティブストロークへ単点を追加する。
    state = _STROKE_STATE
    if state is None:
        return
    x, y = uv_to_pixel(uv, state.layer.buffer.width, state.layer.buffer.height)
    _stroke_paint_pixels(x, y, x, y)


def paint_stroke_segment(context, uv_from, uv_to) -> None:
    # アクティブストロークへ線分を追加する。
    state = _STROKE_STATE
    if state is None:
        return
    x0, y0 = uv_to_pixel(uv_from, state.layer.buffer.width, state.layer.buffer.height)
    x1, y1 = uv_to_pixel(uv_to, state.layer.buffer.width, state.layer.buffer.height)
    _stroke_paint_pixels(x0, y0, x1, y1)


def end_paint_stroke() -> None:
    # ストローク状態を破棄する（結果は buffer 側に反映済み）。
    global _STROKE_STATE
    _STROKE_STATE = None


def paint_stroke_uv(buffer: PixelBuffer, uv_points, color_rgba, radius_px, hardness=1.0) -> None:
    # UV 点列をピクセル座標へ変換し、ストロークを描画する。
    if not uv_points:
        return
    w, h = buffer.width, buffer.height
    px = [uv_to_pixel(uv, w, h) for uv in uv_points]
    if len(px) == 1:
        _stamp_disc(buffer, px[0][0], px[0][1], radius_px, color_rgba, hardness=hardness)
        return
    for (xa, ya), (xb, yb) in zip(px[:-1], px[1:]):
        _paint_segment(buffer, xa, ya, xb, yb, color_rgba, radius_px, hardness=hardness)


# --- Pixel layer ---


def _image_name(scene) -> str:
    # シーン名に紐づくペイント画像名を生成する。
    return f"{_IMAGE_PREFIX}{scene.name}"


def _apply_colorspace(image: bpy.types.Image) -> None:
    # 利用可能な候補の中から画像の色空間を設定する。
    for name in ("Non-Color", "Linear Rec.709", "sRGB"):
        try:
            image.colorspace_settings.name = name
            return
        except TypeError:
            continue


class PaintPixelLayer:
    # PixelBuffer と Blender Image / GPUTexture の同期を担う層。
    __slots__ = ("buffer", "image", "_gpu_texture", "_gpu_size", "_flip_cache", "_last_upload")

    def __init__(self, image, buffer):
        # 画像とバッファのペアを保持し、GPU キャッシュを初期化する。
        self.image = image
        self.buffer = buffer
        self._gpu_texture = None
        self._gpu_size = (0, 0)
        self._flip_cache = None
        self._last_upload = 0.0

    @classmethod
    def create(cls, scene, width, height):
        # シーン用画像を作成/取得して新規レイヤーを作る。
        name = _image_name(scene)
        image = bpy.data.images.get(name) or bpy.data.images.new(name, width, height, alpha=True)
        if int(image.size[0]) != width or int(image.size[1]) != height:
            image.scale(width, height)
        _apply_colorspace(image)
        layer = cls(image, PixelBuffer(width, height))
        layer.flush_to_image()
        layer.upload_gpu(force=True)
        return layer

    @classmethod
    def from_image(cls, image):
        # 既存画像からバッファを復元してレイヤー化する。
        w, h = int(image.size[0]), int(image.size[1])
        _apply_colorspace(image)
        buf = (
            PixelBuffer.from_image_pixels(w, h, image.pixels)
            if len(image.pixels) >= w * h * 4
            else PixelBuffer(w, h)
        )
        return cls(image, buf)

    def clear(self) -> None:
        # バッファをクリアし、GPU 用キャッシュを破棄する。
        self.buffer.clear()
        self._flip_cache = None

    def flush_to_image(self) -> None:
        # バッファ内容を Blender Image に書き戻す。
        w, h = self.buffer.width, self.buffer.height
        if len(self.image.pixels) != w * h * 4:
            self.image.scale(w, h)
        flat = np.ascontiguousarray(np.flipud(self.buffer.pixels).astype(np.float32) / 255.0).reshape(-1)
        self.image.pixels.foreach_set(flat)
        self.image.update()
        self._gpu_texture = None
        self._flip_cache = None

    def invalidate_gpu(self) -> None:
        # 次回アップロードのために CPU→GPU 変換キャッシュを無効化する。
        self._flip_cache = None

    def upload_gpu(self, *, force=False, interactive=False) -> None:
        # dirty 状態や FPS 制限を考慮して GPU テクスチャを更新する。
        w, h = self.buffer.width, self.buffer.height
        dirty = self.buffer.has_dirty() or self.buffer.peek_dirty_rect() is not None
        if not force and not dirty and self._gpu_texture and self._gpu_size == (w, h):
            return
        if interactive and not force and self._gpu_texture:
            if time.monotonic() - self._last_upload < 1.0 / _GPU_FPS:
                return
        if self._flip_cache is None:
            self._flip_cache = np.ascontiguousarray(
                np.flipud(self.buffer.pixels).astype(np.float32) / 255.0
            )
        buf = gpu.types.Buffer("FLOAT", w * h * 4, self._flip_cache)
        self._gpu_texture = gpu.types.GPUTexture((w, h), format="RGBA32F", data=buf)
        self._gpu_size = (w, h)
        self._last_upload = time.monotonic()
        if dirty:
            self.buffer.consume_dirty_rect()

    def get_gpu_texture(self, *, interactive=False):
        # 必要に応じて更新した GPU テクスチャを返す。
        self.upload_gpu(interactive=interactive)
        return self._gpu_texture

    def free_gpu(self) -> None:
        # GPU 関連リソース参照をクリアする。
        self._gpu_texture = None
        self._gpu_size = (0, 0)
        self._flip_cache = None


# --- Document access ---


def get_pixel_layer(context) -> PaintPixelLayer | None:
    # セッションに対応するレイヤーを取得し、必要なら生成/復元する。
    session = get_session(context)
    scene = context.scene
    w, h = session.canvas.texture_width, session.canvas.texture_height
    image = session.document.paint_image
    if image is None:
        image = bpy.data.images.get(_image_name(scene))
        if image:
            session.document.paint_image = image
    if image is None:
        layer = PaintPixelLayer.create(scene, w, h)
        session.document.paint_image = layer.image
        _LAYER_CACHE[layer.image.name] = layer
        return layer
    layer = _LAYER_CACHE.get(image.name)
    if layer is None:
        layer = PaintPixelLayer.from_image(image)
        _LAYER_CACHE[image.name] = layer
    elif layer.buffer.width != w or layer.buffer.height != h:
        layer.image.scale(w, h)
        layer.buffer = PixelBuffer(w, h)
        layer.flush_to_image()
    return layer


def free_layers() -> None:
    # キャッシュ済みレイヤーの GPU リソースを解放して破棄する。
    end_paint_stroke()
    for layer in _LAYER_CACHE.values():
        layer.free_gpu()
    _LAYER_CACHE.clear()


def paint_segment(context, uv_from, uv_to, color_rgba, radius_px, hardness=1.0) -> None:
    # 2 点間のストロークを現在レイヤーへ描く。
    layer = get_pixel_layer(context)
    if layer is None:
        return
    color = tuple(int(round(max(0.0, min(1.0, c)) * 255.0)) for c in color_rgba[:4])
    if len(color) == 3:
        color = (*color, 255)
    paint_stroke_uv(layer.buffer, [uv_from, uv_to], color, max(1, radius_px), hardness=hardness)
    layer.invalidate_gpu()


def paint_dab(context, uv, color_rgba, radius_px, hardness=1.0) -> None:
    # 1 点ストロークとしてブラシを押す。
    paint_segment(context, uv, uv, color_rgba, radius_px, hardness=hardness)


def clear_paint(context) -> None:
    # 現在レイヤーを単色でクリアし、Image へ反映する。
    layer = get_pixel_layer(context)
    if layer:
        layer.clear()
        layer.flush_to_image()


def sync_paint(context) -> None:
    # 描画内容を GPU と Image の両方へ強制同期する。
    layer = get_pixel_layer(context)
    if layer:
        layer.upload_gpu(force=True)
        layer.flush_to_image()
