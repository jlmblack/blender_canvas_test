import bpy

from .reload_utils import register_classes, unregister_classes


class BLENERADDONTEST_PG_canvas(bpy.types.PropertyGroup):
    target_object: bpy.props.PointerProperty(
        name="対象プレーン",
        type=bpy.types.Object,
    )
    texture_width: bpy.props.IntProperty(name="幅", default=1920, min=64, max=4096)
    texture_height: bpy.props.IntProperty(name="高さ", default=1080, min=64, max=4096)


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
