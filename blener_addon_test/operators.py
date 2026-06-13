import bpy
from mathutils import Vector

from . import viewport
from .paint_data import (
    begin_paint_stroke,
    clear_paint,
    end_paint_stroke,
    get_pixel_layer,
    paint_stroke_dab,
    paint_stroke_segment,
    sync_paint,
)
from .material import apply_paint_material_for_render, ensure_edge_material, restore_edge_material
from .paint_surface import PaintSurface
from .properties import get_session
from .reload_utils import register_classes, reload_addon_package, unregister_classes


class BLENERADDONTEST_OT_create_canvas(bpy.types.Operator):
    # 描画対象のプレーンと関連リソースを作成するオペレーター。
    bl_idname = "bleneraddontest.create_canvas"
    bl_label = "キャンバスを作成"
    bl_options = {"REGISTER", "UNDO"}

    plane_size: bpy.props.FloatProperty(default=2.0, min=0.01)

    def execute(self, context):
        # プレーン作成後、セッションと描画ハンドラを初期化する。
        session = get_session(context)
        bpy.ops.mesh.primitive_plane_add(size=self.plane_size, enter_editmode=False)
        plane = context.active_object
        plane.name = "PaintCanvas"
        plane.hide_viewport = False
        session.canvas.target_object = plane
        layer = get_pixel_layer(context)
        session.document.paint_image = layer.image
        ensure_edge_material(context)
        viewport.ensure_handler()
        viewport.tag_redraw(context)
        self.report({"INFO"}, "キャンバスを作成しました")
        return {"FINISHED"}


class BLENERADDONTEST_OT_paint(bpy.types.Operator):
    # モーダルでマウス入力を受け取り、UV 上へブラシ描画するオペレーター。
    bl_idname = "bleneraddontest.paint"
    bl_label = "ペンで描画"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        # 3Dビューでのみ開始し、モーダル描画状態へ遷移する。
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"WARNING"}, "3D ビューで実行してください")
            return {"CANCELLED"}

        self._surface = PaintSurface(context)
        if not self._surface.is_valid():
            self.report({"WARNING"}, "対象プレーンを設定してください")
            return {"CANCELLED"}

        get_pixel_layer(context)
        self._drawing = False
        self._stroke_active = False
        self._last_uv = None
        get_session(context).is_painting = True
        viewport.ensure_handler()
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({"INFO"}, "左ドラッグで描画 / Esc または右クリックで終了")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        # 入力イベントを処理して、点描/線描や終了処理を行う。
        if context.area is None:
            return self._finish(context, {"CANCELLED"})

        session = get_session(context)
        brush = session.brush
        canvas = session.canvas

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self._finish(context, {"FINISHED"})

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                self._drawing = True
                self._last_uv = self._hit_uv(event)
                if self._last_uv is not None:
                    self._stroke_active = begin_paint_stroke(
                        context, brush.color, int(brush.width), hardness=brush.hardness
                    )
                    if self._stroke_active:
                        paint_stroke_dab(context, self._last_uv)
                    context.area.tag_redraw()
            elif event.value == "RELEASE":
                self._drawing = False
                if self._stroke_active:
                    end_paint_stroke()
                    self._stroke_active = False
                sync_paint(context)
                self._last_uv = None
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE" and self._drawing:
            uv = self._hit_uv(event)
            if uv is not None and self._should_add(
                self._last_uv, uv, canvas.texture_width, canvas.texture_height, brush.spacing_px
            ):
                if self._last_uv is not None:
                    if not self._stroke_active:
                        self._stroke_active = begin_paint_stroke(
                            context, brush.color, int(brush.width), hardness=brush.hardness
                        )
                    if self._stroke_active:
                        paint_stroke_segment(context, self._last_uv, uv)
                else:
                    self._stroke_active = begin_paint_stroke(
                        context, brush.color, int(brush.width), hardness=brush.hardness
                    )
                    if self._stroke_active:
                        paint_stroke_dab(context, uv)
                self._last_uv = uv
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def _finish(self, context, status):
        # 描画終了時に CPU/GPU/Image を同期し、状態を戻す。
        if getattr(self, "_stroke_active", False):
            end_paint_stroke()
            self._stroke_active = False
        sync_paint(context)
        get_session(context).is_painting = False
        viewport.tag_redraw(context)
        return status

    def cancel(self, context):
        # Blender からキャンセルされた場合の後始末。
        return self._finish(context, {"CANCELLED"})

    def _hit_uv(self, event):
        # マウス位置を対象プレーン上のUV座標へ変換する。
        hit = self._surface.raycast_event(event)
        return self._surface.world_to_uv(hit) if hit else None

    @staticmethod
    def _should_add(last_uv, uv, width, height, spacing_px):
        # ブラシ間隔(spacing)を満たす場合のみ次の点を打つ。
        from .paint_data import uv_to_pixel

        if last_uv is None:
            return True
        p0 = uv_to_pixel(last_uv, width, height)
        p1 = uv_to_pixel(uv, width, height)
        return (Vector(p0) - Vector(p1)).length >= spacing_px


class BLENERADDONTEST_OT_clear_paint(bpy.types.Operator):
    # ペイントレイヤーをクリアするオペレーター。
    bl_idname = "bleneraddontest.clear_paint"
    bl_label = "消去"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # クリア後にビューポート再描画を要求する。
        clear_paint(context)
        viewport.tag_redraw(context)
        return {"FINISHED"}


class BLENERADDONTEST_OT_restore_edge_material(bpy.types.Operator):
    # 通常表示用(透明)マテリアルへ戻すオペレーター。
    bl_idname = "bleneraddontest.restore_edge_material"
    bl_label = "エッジマテリアルに戻す"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # 対象がある場合のみ復元し、ビュー更新する。
        if get_session(context).canvas.target_object is None:
            self.report({"WARNING"}, "対象プレーンを設定してください")
            return {"CANCELLED"}
        restore_edge_material(context)
        viewport.tag_redraw(context)
        self.report({"INFO"}, "エッジマテリアルに戻しました")
        return {"FINISHED"}


class BLENERADDONTEST_OT_preview_render_material(bpy.types.Operator):
    # レンダー確認用にペイントマテリアルを一時適用する。
    bl_idname = "bleneraddontest.preview_render_material"
    bl_label = "レンダー用マテリアルを一時表示"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # 対象がある場合のみ一時適用し、表示を更新する。
        if get_session(context).canvas.target_object is None:
            self.report({"WARNING"}, "対象プレーンを設定してください")
            return {"CANCELLED"}
        apply_paint_material_for_render(context, show_in_viewport=True)
        obj = get_session(context).canvas.target_object
        obj.hide_viewport = False
        viewport.tag_redraw(context)
        self.report({"INFO"}, "一時表示中。「エッジマテリアルに戻す」で元に戻せます")
        return {"FINISHED"}


class BLENERADDONTEST_OT_reload_modules(bpy.types.Operator):
    # アドオンパッケージを再読み込みする開発用オペレーター。
    bl_idname = "bleneraddontest.reload_modules"
    bl_label = "Reload Addon Modules"

    def execute(self, context):
        # 例外を捕捉してエラーメッセージを表示する。
        try:
            reload_addon_package(__package__)
            self.report({"INFO"}, "Reloaded")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (
    BLENERADDONTEST_OT_create_canvas,
    BLENERADDONTEST_OT_paint,
    BLENERADDONTEST_OT_clear_paint,
    BLENERADDONTEST_OT_preview_render_material,
    BLENERADDONTEST_OT_restore_edge_material,
    BLENERADDONTEST_OT_reload_modules,
)


def register():
    # このモジュールの全オペレーターを登録する。
    register_classes(CLASSES)


def unregister():
    # このモジュールの全オペレーター登録を解除する。
    unregister_classes(CLASSES)
