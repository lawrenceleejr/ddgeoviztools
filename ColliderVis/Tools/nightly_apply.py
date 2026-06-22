"""
nightly_apply.py — one headless pass that:
  1. Reimports the pristine barrel meshes (ECalBarrel, HCalBarrel) in place.
  2. Reimports the regenerated eerie ambience drone (S_AmbienceLoop).
  3. Makes the character CLIP THROUGH all detector / sphere / accelerator geometry
     by setting NoCollision on every StaticMeshActor EXCEPT the two floors
     (Floor_Ground = visible main floor, CutawayWalkFloor = invisible beam-plane
     floor at z=0). CutawayWalkFloor is also hidden in game (invisible but solid).
  4. Saves the map + assets.

Run headless:
    UnrealEditor-Cmd <proj>/ColliderVis.uproject -run=pythonscript \
        -script="<proj>/Tools/nightly_apply.py" -unattended -nosplash
"""
import unreal
from pathlib import Path

PROJ = Path(unreal.Paths.project_dir())
MAP = "/Game/Maps/ColliderVisMain"

# Floors to KEEP solid (by actor label, lower-cased). Everything else -> clip-through.
KEEP_LABELS = {"floor_ground", "cutawaywalkfloor"}
HIDE_LABELS = {"cutawaywalkfloor"}  # invisible but still collidable


def _task(src: Path, dest_path: str, name: str) -> unreal.AssetImportTask:
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", str(src))
    t.set_editor_property("destination_path", dest_path)
    t.set_editor_property("destination_name", name)
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("replace_existing_settings", False)
    t.set_editor_property("save", True)
    return t


def main():
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    tasks = [
        _task(PROJ / "ue5_meshes" / "ECalBarrel.glb", "/Game/Detector", "ECalBarrel"),
        _task(PROJ / "ue5_meshes" / "HCalBarrel.glb", "/Game/Detector", "HCalBarrel"),
        _task(PROJ / "Content" / "Audio" / "Source" / "ambience_loop.wav", "/Game/Audio", "S_AmbienceLoop"),
    ]
    tools.import_asset_tasks(tasks)
    print("NIGHTLY_APPLY: reimported barrels + ambience")

    world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    ess = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    nocol = kept = hidden = 0
    for a in ess.get_all_level_actors():
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        label = a.get_actor_label().lower()
        comp = a.static_mesh_component
        if comp is None:
            continue
        if label in KEEP_LABELS:
            comp.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
            comp.set_collision_profile_name("BlockAll")
            kept += 1
            tag = "KEEP "
        else:
            comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            nocol += 1
            tag = "NOCOL"
        if label in HIDE_LABELS:
            a.set_actor_hidden_in_game(True)
            hidden += 1
        print(f"  {tag} {a.get_name()} '{a.get_actor_label()}'")

    unreal.EditorLoadingAndSavingUtils.save_map(world, MAP)
    print(f"COLLIDERVIS_APPLY_RESULT nocol={nocol} kept={kept} hidden={hidden}")


main()
