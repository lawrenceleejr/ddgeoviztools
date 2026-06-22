"""
fix_cutaway_blend.py — force M_DetectorGeometry to BLEND_Masked via the real API.

The phi-quadrant cutaway clips via the material's OpacityMask, which only takes
effect when the material's blend mode is Masked. Setting blend_mode through the
MCP ObjectTools.set_properties is edit-gated (it reports BLEND_Masked on read-back
but the COMPILED material stays Opaque, so OpacityMask is ignored and nothing
clips). The editor-property API below actually applies + recompiles it.

Run headless (editor closed):
    UnrealEditor-Cmd <proj>/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/Tools/fix_cutaway_blend.py"
"""
import unreal

P = "/Game/Materials/M_DetectorGeometry"


def run():
    m = unreal.EditorAssetLibrary.load_asset(P)
    if m is None:
        unreal.log_warning("CUTAWAY_BLEND: material not found")
        return
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    m.set_editor_property("two_sided", True)
    m.set_editor_property("opacity_mask_clip_value", 0.5)
    unreal.MaterialEditingLibrary.recompile_material(m)
    unreal.EditorAssetLibrary.save_asset(P)
    unreal.log_warning("CUTAWAY_BLEND set: blend=%s twosided=%s clip=%s" % (
        str(m.get_editor_property("blend_mode")),
        str(m.get_editor_property("two_sided")),
        str(m.get_editor_property("opacity_mask_clip_value"))))


if __name__ == "__main__":
    run()
