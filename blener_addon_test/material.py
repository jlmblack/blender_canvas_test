"""デフォルトは透明マテリアル。レンダー時だけペイントマテリアルを一時適用。"""

import bpy

from .paint_data import get_pixel_layer, sync_paint
from .properties import get_session

_EDGE_MATERIAL_NAME = "BlenerPaintEdgeMaterial"
_PAINT_MATERIAL_NAME = "BlenerPaintMaterial"
_render_swap_active = False


def _find_image_node(node_tree):
    for node in node_tree.nodes:
        if node.type == "TEX_IMAGE":
            return node
    return None


def _setup_paint_material_nodes(mat, image):
    mat.use_nodes = True
    mat.blend_method = "BLEND"
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"

    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-200, 0)
    tex.image = image
    tex.interpolation = "Closest"

    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def _setup_edge_material_nodes(mat):
    """ビューポート描画と競合しないよう、オブジェクトを完全透明にする。"""
    mat.use_nodes = True
    mat.blend_method = "BLEND"
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"

    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (260, 0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 0)
    links.new(transparent.outputs["BSDF"], output.inputs["Surface"])
    return mat


def _get_paint_material(image):
    mat = bpy.data.materials.get(_PAINT_MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(_PAINT_MATERIAL_NAME)
        _setup_paint_material_nodes(mat, image)
    else:
        tex_node = _find_image_node(mat.node_tree)
        if tex_node is None:
            _setup_paint_material_nodes(mat, image)
        else:
            tex_node.image = image
    return mat


def _is_edge_material_valid(mat):
    if not mat.use_nodes or mat.node_tree is None:
        return False
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_TRANSPARENT":
            return True
    return False


def _get_edge_material():
    mat = bpy.data.materials.get(_EDGE_MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(_EDGE_MATERIAL_NAME)
    if not _is_edge_material_valid(mat):
        _setup_edge_material_nodes(mat)
    return mat


def _assign_material(obj, mat):
    if len(obj.data.materials) == 0:
        obj.data.materials.append(mat)
    else:
        obj.data.materials[0] = mat


def ensure_edge_material(context):
    """対象プレーンに透明マテリアルを割り当てる。"""
    session = get_session(context)
    obj = session.canvas.target_object
    if obj is None or obj.type != "MESH":
        return None

    mat = _get_edge_material()
    _assign_material(obj, mat)
    return mat


def apply_paint_material_for_render(context, *, show_in_viewport=False):
    """レンダー用にペイントマテリアルを一時適用。"""
    global _render_swap_active

    session = get_session(context)
    obj = session.canvas.target_object
    if obj is None or obj.type != "MESH":
        return None

    sync_paint(context)
    layer = get_pixel_layer(context)
    if layer is None:
        return None

    mat = _get_paint_material(layer.image)
    _assign_material(obj, mat)
    if show_in_viewport:
        obj.hide_viewport = False
    _render_swap_active = True
    return mat


def restore_edge_material(context):
    """ペイントマテリアルを外し、エッジマテリアルへ戻す。"""
    global _render_swap_active

    session = get_session(context)
    obj = session.canvas.target_object
    if obj is None or obj.type != "MESH":
        _render_swap_active = False
        return None

    mat = ensure_edge_material(context)
    obj.hide_viewport = True
    _render_swap_active = False
    return mat


def register_handlers():
    for handler in (_on_render_pre, _on_render_post, _on_render_complete):
        bucket = _handler_bucket(handler)
        if handler not in bucket:
            bucket.append(handler)


def unregister_handlers():
    for handler in (_on_render_pre, _on_render_post, _on_render_complete):
        bucket = _handler_bucket(handler)
        if handler in bucket:
            bucket.remove(handler)


def _handler_bucket(handler):
    if handler is _on_render_pre:
        return bpy.app.handlers.render_pre
    if handler is _on_render_post:
        return bpy.app.handlers.render_post
    return bpy.app.handlers.render_complete


def _try_render_context():
    ctx = bpy.context
    if not hasattr(ctx, "scene") or not hasattr(ctx.scene, "bleneraddontest"):
        return None
    if ctx.scene.bleneraddontest.canvas.target_object is None:
        return None
    return ctx


@bpy.app.handlers.persistent
def _on_render_pre(_scene, _depsgraph=None):
    ctx = _try_render_context()
    if ctx is None:
        return
    try:
        apply_paint_material_for_render(ctx)
    except Exception:
        import traceback

        print("[Paint Canvas] render_pre failed:")
        traceback.print_exc()


@bpy.app.handlers.persistent
def _on_render_post(_scene, _depsgraph=None):
    ctx = _try_render_context()
    if ctx is None:
        return
    try:
        restore_edge_material(ctx)
    except Exception:
        import traceback

        print("[Paint Canvas] render_post failed:")
        traceback.print_exc()


@bpy.app.handlers.persistent
def _on_render_complete(_scene, _depsgraph=None):
    ctx = _try_render_context()
    if ctx is None:
        return
    try:
        restore_edge_material(ctx)
    except Exception:
        import traceback

        print("[Paint Canvas] render_complete failed:")
        traceback.print_exc()
