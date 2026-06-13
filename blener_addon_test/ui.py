import bpy


from .reload_utils import register_classes, unregister_classes


class BLENERADDONTEST_PT_panel(bpy.types.Panel):

    bl_label = "Paint Canvas"
    bl_idname = "BLENERADDONTEST_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Addon Test"

    def draw(self, context):
        layout = self.layout
        s = context.scene.bleneraddontest
        box = layout.box()
        box.label(text="キャンバス", icon="MESH_PLANE")
        box.operator("bleneraddontest.create_canvas", icon="ADD")
        box.prop(s.canvas, "target_object")
        row = box.row(align=True)
        row.prop(s.canvas, "texture_width", text="W")
        row.prop(s.canvas, "texture_height", text="H")
        box = layout.box()
        box.label(text="ペン", icon="GREASEPENCIL")
        box.operator("bleneraddontest.paint", icon="EDITMODE_HLT")
        box.operator("bleneraddontest.clear_paint", icon="TRASH")
        box.prop(s.brush, "color")
        box.prop(s.brush, "width")
        box.prop(s.brush, "hardness")
        box.prop(s.brush, "spacing_px")
        box = layout.box()
        box.label(text="レンダー", icon="RENDER_STILL")
        box.operator("bleneraddontest.preview_render_material", icon="MATERIAL")
        box.operator("bleneraddontest.restore_edge_material", icon="LOOP_BACK")
        box.label(text="F12 時は自動で一時適用→復元", icon="INFO")
        layout.operator("bleneraddontest.reload_modules", icon="FILE_REFRESH")


classes = (BLENERADDONTEST_PT_panel,)


def register():

    register_classes(classes)


def unregister():

    unregister_classes(classes)
