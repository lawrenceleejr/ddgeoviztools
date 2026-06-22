"""
set_accel_nocollision.py — make the generated accelerator/hall geometry clip-through.

The procedurally-placed AccelHall (a scaled engine Cylinder) has SOLID simple
collision, so its whole interior is "inside collision" and the player pawn gets
ejected to the shell on spawn. AccelBeamPipe + AccelMag_* likewise block the
player. Set them all to NO_COLLISION so the player walks on the floor inside the
visual hall and can move freely around the beamline (matches the rest of the
detector geometry, which is also clip-through).

collisionEnabled can't be changed via the MCP ObjectTools.set_properties (edit-
gated); the real component API works. Headless level edits must use
LevelEditorSubsystem.load_level + save_current_level (NOT EditorLoadingAndSavingUtils).

Run headless (editor MUST be closed):
    UnrealEditor-Cmd <proj>/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/Tools/set_accel_nocollision.py"
"""
import unreal

LEVEL = "/Game/Maps/ColliderVisMain"


def run():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.load_level(LEVEL)

    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = eas.get_all_level_actors()

    changed = 0
    for a in actors:
        lbl = a.get_actor_label()
        if not (lbl.startswith("AccelMag_") or lbl in ("AccelHall", "AccelBeamPipe")):
            continue
        comps = a.get_components_by_class(unreal.StaticMeshComponent)
        for c in comps:
            c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            c.set_collision_profile_name("NoCollision")
        changed += 1
        unreal.log_warning("NOCOLLISION: %s" % lbl)

    les.save_current_level()
    unreal.log_warning("COLLIDERVIS_NOCOLLISION=%d" % changed)


if __name__ == "__main__":
    run()
