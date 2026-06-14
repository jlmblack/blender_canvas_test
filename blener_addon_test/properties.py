import bpy

from .reload_utils import register_classes, unregister_classes


def _on_canvas_size_update(_self, context):
    # UI 上の W/H 変更を即時にレイヤーとプレーン比率へ反映する。
    if context is None or not hasattr(context, "scene"):
        return
    if not hasattr(context.scene, "bleneraddontest"):
        return
    session = context.scene.bleneraddontest
    tex_w = int(session.canvas.texture_width)
    tex_h = int(session.canvas.texture_height)
    print(f"[AspectDebug:properties.update] requested tex={tex_w}x{tex_h}")
    from .paint_data import get_pixel_layer
    from .viewport import tag_redraw

    get_pixel_layer(context)
    obj = session.canvas.target_object
    if obj is not None and obj.type == "MESH":
        # プロパティ更新直後の評価順差を吸収するため、依存グラフを明示更新する。
        if getattr(context, "view_layer", None) is not None:
            context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        if hasattr(depsgraph, "update"):
            depsgraph.update()
        sx, sy, sz = (float(v) for v in obj.scale)
        mx, my, mz = (float(v) for v in obj.matrix_world.to_scale())
        eval_obj = obj.evaluated_get(depsgraph)
        ex, ey, ez = (float(v) for v in eval_obj.matrix_world.to_scale())
        print(
            "[AspectDebug:properties.update] "
            f"local_scale=({sx:.6f}, {sy:.6f}, {sz:.6f}) local_ratio={(sx / sy) if abs(sy) > 1e-12 else float('inf'):.6f} "
            f"matrix_scale=({mx:.6f}, {my:.6f}, {mz:.6f}) matrix_ratio={(mx / my) if abs(my) > 1e-12 else float('inf'):.6f} "
            f"eval_matrix_scale=({ex:.6f}, {ey:.6f}, {ez:.6f}) eval_ratio={(ex / ey) if abs(ey) > 1e-12 else float('inf'):.6f}"
        )
    else:
        print("[AspectDebug:properties.update] skip matrix check (target object is None)")
    tag_redraw(context)


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
