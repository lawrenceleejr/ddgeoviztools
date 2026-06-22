"""
set_collision2.py — headless, robust clip-through collision.

Uses the REAL UPrimitiveComponent setters (set_collision_enabled /
set_collision_profile_name) — MCP set_properties cannot change collisionEnabled
(it's edit-gated), so this is the reliable path. Loads the level via
LevelEditorSubsystem, sets NoCollision on every StaticMeshActor EXCEPT the two
floors (Floor_Ground, CutawayWalkFloor -> BlockAll), hides CutawayWalkFloor
(invisible but solid), saves the level, and logs counts via log_warning so the
result is visible in the headless log.

Run with the editor CLOSED:
    UnrealEditor-Cmd <proj>/ColliderVis.uproject -run=pythonscript \
        -script="<proj>/Tools/set_collision2.py" -unattended -nosplash
"""
import unreal

MAP = "/Game/Maps/ColliderVisMain"
KEEP = {"floor_ground", "cutawaywalkfloor"}
HIDE = {"cutawaywalkfloor"}


def log(m):
    unreal.log_warning("COLLISION2: " + str(m))


les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level(MAP)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = eas.get_all_level_actors()
log("level actors = %d" % len(actors))

nocol = kept = hidden = 0
for a in actors:
    if not isinstance(a, unreal.StaticMeshActor):
        continue
    label = a.get_actor_label().lower()
    comp = a.static_mesh_component
    if comp is None:
        continue
    if label in KEEP:
        comp.set_collision_profile_name("BlockAll")
        comp.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
        kept += 1
    else:
        comp.set_collision_profile_name("NoCollision")
        comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        nocol += 1
    if label in HIDE:
        comp.set_visibility(False, True)
        a.set_actor_hidden_in_game(True)
        hidden += 1

log("set NoCollision=%d  BlockAll(floors)=%d  hidden=%d" % (nocol, kept, hidden))

saved = les.save_current_level()
log("save_current_level -> %s" % saved)

# Verify a representative detector actor really reads NoCollision now.
for a in actors:
    if isinstance(a, unreal.StaticMeshActor) and a.get_actor_label().lower() == "detector_ecalbarrel":
        ce = a.static_mesh_component.get_collision_enabled()
        log("VERIFY detector_ecalbarrel collisionEnabled = %s" % ce)
        break

log("DONE")
