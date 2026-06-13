import gpu

_paint_shader = None
_edge_shader = None


def get_paint_shader():
    global _paint_shader
    if _paint_shader is not None:
        return _paint_shader

    vert_out = gpu.types.GPUStageInterfaceInfo("paint_iface")
    vert_out.smooth("VEC2", "uv_interp")

    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "viewProjectionMatrix")
    info.push_constant("MAT4", "modelMatrix")
    info.sampler(0, "FLOAT_2D", "image")
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "VEC2", "uv")
    info.vertex_out(vert_out)
    info.fragment_out(0, "VEC4", "FragColor")
    info.vertex_source(
        "void main() {"
        "  uv_interp = uv;"
        "  vec4 world = modelMatrix * vec4(pos, 1.0);"
        "  vec3 normal = normalize(mat3(modelMatrix) * vec3(0.0, 0.0, 1.0));"
        "  world.xyz += normal * 0.001;"
        "  gl_Position = viewProjectionMatrix * world;"
        "}"
    )
    info.fragment_source(
        "void main() {"
        "  ivec2 size_px = textureSize(image, 0);"
        "  vec2 uv = clamp(uv_interp, vec2(0.0), vec2(1.0));"
        "  vec2 texel = floor(uv * vec2(size_px));"
        "  ivec2 p = ivec2(clamp(texel, vec2(0.0), vec2(size_px) - vec2(1.0)));"
        "  FragColor = texelFetch(image, p, 0);"
        "}"
    )

    _paint_shader = gpu.shader.create_from_info(info)
    del vert_out, info
    return _paint_shader


def get_edge_shader():
    global _edge_shader
    if _edge_shader is not None:
        return _edge_shader

    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "viewProjectionMatrix")
    info.push_constant("MAT4", "modelMatrix")
    info.push_constant("VEC4", "edgeColor")
    info.vertex_in(0, "VEC3", "pos")
    info.fragment_out(0, "VEC4", "FragColor")
    info.vertex_source(
        "void main() {"
        "  vec4 world = modelMatrix * vec4(pos, 1.0);"
        "  vec3 normal = normalize(mat3(modelMatrix) * vec3(0.0, 0.0, 1.0));"
        "  world.xyz += normal * 0.002;"
        "  gl_Position = viewProjectionMatrix * world;"
        "}"
    )
    info.fragment_source("void main() { FragColor = edgeColor; }")

    _edge_shader = gpu.shader.create_from_info(info)
    del info
    return _edge_shader


def free_paint_shader():
    global _paint_shader, _edge_shader
    _paint_shader = None
    _edge_shader = None
