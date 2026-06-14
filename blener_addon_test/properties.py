import bpy
from types import SimpleNamespace

from .reload_utils import register_classes, unregister_classes

_CANVAS_SIZE_DEBOUNCE_SEC = 0.18
_CANVAS_UPDATE_TOKEN = 0


def _apply_canvas_size_update(scene_name: str, token: int):
    # 最後の入力だけ反映するため、古いタイマー呼び出しは破棄する。
    global _CANVAS_UPDATE_TOKEN
    if token != _CANVAS_UPDATE_TOKEN:
        return None

    scene = bpy.data.scenes.get(scene_name)
    if scene is None or not hasattr(scene, "bleneraddontest"):
        return None

    session = scene.bleneraddontest
    from .paint_data import get_pixel_layer
    from .viewport import tag_redraw

    # get_pixel_layer は context.scene だけ参照するため、最小コンテキストで呼ぶ。
    get_pixel_layer(SimpleNamespace(scene=scene))

    obj = session.canvas.target_object
    if obj is not None and obj.type == "MESH":
        obj.update_tag(refresh={"OBJECT"})
        print(
            "[AspectDebug:properties.debounced_apply] "
            f"tex={int(session.canvas.texture_width)}x{int(session.canvas.texture_height)} "
            f"scale=({obj.scale[0]:.6f}, {obj.scale[1]:.6f}, {obj.scale[2]:.6f})"
        )
    tag_redraw(bpy.context)
    return None


def _on_canvas_size_update(_self, context):
    # スライド中の連続更新を避け、入力が止まってから 1 回だけ反映する。
    global _CANVAS_UPDATE_TOKEN
    if context is None or not hasattr(context, "scene"):
        return
    if not hasattr(context.scene, "bleneraddontest"):
        return
    _CANVAS_UPDATE_TOKEN += 1
    token = _CANVAS_UPDATE_TOKEN
    scene_name = context.scene.name
    print(
        f"[AspectDebug:properties.update] schedule token={token} "
        f"tex={int(context.scene.bleneraddontest.canvas.texture_width)}x"
        f"{int(context.scene.bleneraddontest.canvas.texture_height)}"
    )
    bpy.app.timers.register(
        lambda: _apply_canvas_size_update(scene_name, token),
        first_interval=_CANVAS_SIZE_DEBOUNCE_SEC,
    )


class BLENERADDONTEST_PG_canvas(bpy.types.PropertyGroup):
    target_object: bpy.props.PointerProperty(
        name="対象プレーン",
        type=bpy.types.Object,
    )
    texture_width: bpy.props.IntProperty(
        name="幅", default=1920, min=64, max=4096, update=_on_canvas_size_update
    )
    texture_height: bpy.props.IntProperty(
        name="高さ", default=1080, min=64, max=4096, update=_on_canvas_size_update
    )


class BLENERADDONTEST_PG_brush(bpy.types.PropertyGroup):
    color: bpy.props.FloatVectorProperty(
        name="色",
        subtype="COLOR",
        size=4,
        default=(0.1, 0.6, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )
    width: bpy.props.FloatProperty(name="半径 (px)", default=3.0, min=1.0, max=20.0)
    hardness: bpy.props.FloatProperty(name="硬さ", default=1.0, min=0.0, max=1.0)
    spacing_px: bpy.props.IntProperty(name="点の間隔 (px)", default=4, min=1, max=64)


class BLENERADDONTEST_PG_document(bpy.types.PropertyGroup):
    paint_image: bpy.props.PointerProperty(name="ペイント画像", type=bpy.types.Image)


class BLENERADDONTEST_PG_session(bpy.types.PropertyGroup):
    canvas: bpy.props.PointerProperty(type=BLENERADDONTEST_PG_canvas)
    brush: bpy.props.PointerProperty(type=BLENERADDONTEST_PG_brush)
    document: bpy.props.PointerProperty(type=BLENERADDONTEST_PG_document)
    is_painting: bpy.props.BoolProperty(name="描画中", default=False, options={"HIDDEN"})


_CLASSES = (
    BLENERADDONTEST_PG_canvas,
    BLENERADDONTEST_PG_brush,
    BLENERADDONTEST_PG_document,
    BLENERADDONTEST_PG_session,
)


def get_session(context):
    return context.scene.bleneraddontest


def register():
    register_classes(_CLASSES)
    bpy.types.Scene.bleneraddontest = bpy.props.PointerProperty(type=BLENERADDONTEST_PG_session)


def unregister():
    if hasattr(bpy.types.Scene, "bleneraddontest"):
        del bpy.types.Scene.bleneraddontest
    unregister_classes(_CLASSES)
