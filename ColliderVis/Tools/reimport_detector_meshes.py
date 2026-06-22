"""
reimport_detector_meshes.py — headless reimporter for the cleaned detector barrel meshes.

After AGENT-MESHFIX2 stripped the exact-origin (0,0,0) degenerate triangles from
the source binary glTF files (editing ONLY the index accessor; POSITION/NORMAL
vertex buffers left byte-identical), this script reimports the cleaned GLBs back
over the EXISTING static-mesh assets, replacing them in place so every reference
(C++, Blueprints, placed actors) stays intact.

MESHFIX2 modified ONLY ECalBarrel.glb (56 tris removed) and HCalBarrel.glb
(114 tris removed). All other source GLBs were inspected and left UNCHANGED
(no exact-origin verts, no separable envelope, no hull-able layer stacks).

SOURCE -> ASSET CONTRACT
------------------------
    ue5_meshes/ECalBarrel.glb  ->  /Game/Detector/ECalBarrel
    ue5_meshes/HCalBarrel.glb  ->  /Game/Detector/HCalBarrel

How to run
----------
Headless (the orchestrator's path):

    UnrealEditor-Cmd <proj>/ColliderVis/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/ColliderVis/Tools/reimport_detector_meshes.py"

From a live editor's Python console:

    py "<proj>/ColliderVis/Tools/reimport_detector_meshes.py"

Design notes
------------
* Replace-in-place: AssetImportTask(replace_existing=True, save=True) re-imports
  over the asset at the SAME /Game/Detector path, so references are never broken.
* Idempotent: re-running just re-imports the current GLB contents again.
* Self-reporting: ends by printing a single COLLIDERVIS_REIMPORT_RESULT=<json>
  line so an automated agent can parse stdout and react.
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

try:
    import unreal
except ImportError:
    unreal = None


# ─────────────────────────────────────────────────────────────────────────────
# Paths / contracts
# ─────────────────────────────────────────────────────────────────────────────

DEST_PATH = "/Game/Detector"

# Source GLB filename (under <proj>/ue5_meshes/) -> /Game/Detector asset name.
MESH_MAP = {
    "ECalBarrel.glb": "ECalBarrel",
    "HCalBarrel.glb": "HCalBarrel",
    # Endcaps reimported to rebuild render/Nanite data (invalidated by the barrel
    # reimport); their source GLBs are unmodified originals.
    "ECalEndcap.glb": "ECalEndcap",
    "HCalEndcap.glb": "HCalEndcap",
}


def _project_dir() -> Path:
    """Project root (folder containing ColliderVis.uproject)."""
    if unreal is not None:
        return Path(unreal.Paths.project_dir())
    # Fallback when run outside the editor: this file is <proj>/Tools/<this>.py
    return Path(__file__).resolve().parent.parent


def _meshes_dir() -> Path:
    return _project_dir() / "ue5_meshes"


def reimport_meshes(args=None):
    result = {"imported": [], "skipped": [], "errors": []}

    if unreal is None:
        msg = "unreal module unavailable — run inside UnrealEditor-Cmd -run=pythonscript"
        result["errors"].append(msg)
        print("COLLIDERVIS_REIMPORT_RESULT=" + json.dumps(result))
        return result

    mesh_dir = _meshes_dir()
    if not mesh_dir.is_dir():
        result["errors"].append(f"mesh source dir not found: {mesh_dir}")
        print("COLLIDERVIS_REIMPORT_RESULT=" + json.dumps(result))
        return result

    tools = unreal.AssetToolsHelpers.get_asset_tools()

    tasks = []
    for src_name, asset_name in MESH_MAP.items():
        src = mesh_dir / src_name
        if not src.is_file():
            result["errors"].append(f"source GLB missing: {src}")
            continue
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(src))
        task.set_editor_property("destination_path", DEST_PATH)
        task.set_editor_property("destination_name", asset_name)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("replace_existing_settings", False)
        task.set_editor_property("save", True)
        tasks.append((src, asset_name, task))

    if tasks:
        try:
            tools.import_asset_tasks([t for _, _, t in tasks])
        except Exception as exc:  # noqa: BLE001
            result["errors"].append("import_asset_tasks failed: " + repr(exc))
            traceback.print_exc()

    # Verify each expected asset now exists at /Game/Detector/<name>.
    for src, asset_name, _task in tasks:
        asset_path = f"{DEST_PATH}/{asset_name}"
        obj_path = f"{asset_path}.{asset_name}"
        try:
            exists = unreal.EditorAssetLibrary.does_asset_exist(asset_path)
        except Exception:  # noqa: BLE001
            exists = False
        if exists:
            result["imported"].append({"source": src.name, "asset": obj_path})
        else:
            result["errors"].append(
                {"source": src.name, "expected": obj_path,
                 "status": "not found after import"})

    try:
        unreal.EditorAssetLibrary.save_directory(DEST_PATH, only_if_is_dirty=False)
    except Exception:  # noqa: BLE001
        pass

    print("COLLIDERVIS_REIMPORT_RESULT=" + json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reimport cleaned detector barrel GLBs into /Game/Detector")
    # Accept/ignore unknown args so it survives UnrealEditor-Cmd's extra argv.
    args, _unknown = parser.parse_known_args(sys.argv[1:])
    reimport_meshes(args)
