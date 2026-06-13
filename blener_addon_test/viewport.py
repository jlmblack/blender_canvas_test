import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from .paint_data import free_layers, get_pixel_layer
from .paint_surface import PaintSurface
from .properties import get_session
from .shader import free_paint_shader, get_edge_shader, get_paint_shader

_draw_handle = None
_paint_batch = None
_edge_batch = None

_EDGE_COLOR = (0.35, 0.35, 0.35, 1.0)


def _draw_edges(surface, region_data):
    global _edge_batch
    if _edge_batch is None:
        coords = (
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
            (-1.0, -1.0, 0.0),
        )
        _edge_batch = batch_for_shader(get_edge_shader(), "LINE_STRIP", {"pos": coords})

    shader = get_edge_shader()
    shader.bind()
    shader.uniform_float("viewProjectionMatrix", region_data.perspective_matrix)
    shader.uniform_float("modelMatrix", surface.matrix_world)
    shader.uniform_float("edgeColor", _EDGE_COLOR)

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)
    gpu.state.line_width_set(1.5)
    _edge_batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.shader.unbind()


def _draw_paint(surface, region_data, gpu_tex):
    global _paint_batch
    if _paint_batch is None:
        coords, uvs = surface.plane_coords()
        _paint_batch = batch_for_shader(
            get_paint_shader(),
            "TRI_FAN",
            {"pos": coords, "uv": uvs},
        )

    shader = get_paint_shader()
    shader.bind()
    shader.uniform_float("viewProjectionMatrix", region_data.perspective_matrix)
    shader.uniform_float("modelMatrix", surface.matrix_world)
    shader.uniform_sampler("image", gpu_tex)

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)
    gpu.state.face_culling_set("NONE")
    _paint_batch.draw(shader)
    gpu.state.face_culling_set("BACK")
    gpu.shader.unbind()


def _draw():
    context = bpy.context
    if not hasattr(context.scene, "bleneraddontest"):
        return

    surface = PaintSurface(context)
    if not surface.is_valid():
        return

    region_data = context.region_data
    if region_data is None:
        return

    _draw_edges(surface, region_data)

    layer = get_pixel_layer(context)
    if layer is None:
        return

    interactive = get_session(context).is_painting
    gpu_tex = layer.get_gpu_texture(interactive=interactive)
    if gpu_tex is None:
        return

    _draw_paint(surface, region_data, gpu_tex)

    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def ensure_handler():
    global _draw_handle
    if _draw_handle is not None:
        return
    _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")


def free_handler():
    global _draw_handle, _paint_batch, _edge_batch
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    _paint_batch = None
    _edge_batch = None
    free_layers()
    free_paint_shader()


def tag_redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
