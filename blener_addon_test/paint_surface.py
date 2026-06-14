"""プレーン上の UV / ワールド座標変換とレイキャスト。"""

from bpy_extras import view3d_utils
from mathutils import Matrix, Quaternion, Vector
from mathutils.geometry import intersect_line_plane

from .properties import get_session

_PLANE_UV_SCALE = 0.5


class PaintSurface:
    def __init__(self, context):
        # Blender のコンテキストと、このアドオン用セッションを保持する。
        self.context = context
        self.session = get_session(context)

    @property
    def target_object(self):
        # 設定済みの描画対象オブジェクトを返す。
        return self.session.canvas.target_object

    @property
    def matrix_world(self) -> Matrix:
        # 対象オブジェクトのワールド行列を返し、無効時は単位行列を返す。
        obj = self.target_object
        if obj is not None and obj.type == "MESH":
            # 親なしオブジェクトは TRS から直接合成し、UI 変更の即時反映を優先する。
            if obj.parent is None:
                if obj.rotation_mode == "QUATERNION":
                    rot = obj.rotation_quaternion.copy()
                elif obj.rotation_mode == "AXIS_ANGLE":
                    angle, ax, ay, az = obj.rotation_axis_angle
                    rot = Quaternion((ax, ay, az), angle)
                else:
                    rot = obj.rotation_euler.to_quaternion()
                return Matrix.LocRotScale(obj.location.copy(), rot, obj.scale.copy())
            return obj.matrix_world.copy()
        return Matrix.Identity(4)

    def is_valid(self) -> bool:
        # 描画対象が有効なメッシュかどうかを判定する。
        obj = self.target_object
        return obj is not None and obj.type == "MESH"

    def raycast_event(self, event) -> Vector | None:
        # マウス座標からビューのレイを作り、対象プレーンとの交点(ワールド座標)を返す。
        region = self.context.region
        region_data = self.context.region_data
        if region is None or region_data is None:
            return None

        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
        plane_co = self.matrix_world.translation
        plane_no = self.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
        return intersect_line_plane(origin, origin + direction, plane_co, plane_no)

    def world_to_uv(self, world_co: Vector) -> Vector:
        # ワールド座標を対象プレーンのUV座標(0..1)に変換する。
        local = self.matrix_world.inverted() @ world_co
        return Vector((local.x * _PLANE_UV_SCALE + 0.5, local.y * _PLANE_UV_SCALE + 0.5))

    def plane_coords(self):
        # プレーン描画に使う頂点座標と対応UVを返す。
        return (
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
        ), (
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
        )
