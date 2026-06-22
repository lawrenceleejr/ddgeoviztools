"""
reimport_simplified.py — reimport the simplified detector glTFs from ../data/output
over the existing /Game/Detector/* static-mesh assets, in place.

The simplify/export pipeline drops self-contained *.gltf (embedded buffers) into
<repo>/data/output/, one per sub-detector, filename == asset name:

    ../data/output/ECalBarrel.gltf   ->  /Game/Detector/ECalBarrel
    ../data/output/HCalEndcap.gltf   ->  /Game/Detector/HCalEndcap
    ... (every *.gltf present)

Replace-in-place (AssetImportTask replace_existing=True, replace_existing_settings
=False) so existing references (C++, Blueprints, placed actors), material slot
assignments, scale and Nanite settings are all preserved — only the geometry is
swapped. Reports LOD0 triangle counts before & after so the simplification is
verifiable, then prints COLLIDERVIS_REIMPORT_RESULT=<json>.

Run headless (editor MUST be closed):
    UnrealEditor-Cmd <proj>/ColliderVis/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/ColliderVis/Tools/reimport_simplified.py"
"""
import json
import sys
import traceback
from pathlib import Path

try:
    import unreal
except ImportError:
    unreal = None

DEST_PATH = "/Game/Detector"


def _project_dir() -> Path:
    if unreal is not None:
        return Path(unreal.Paths.project_dir())
    return Path(__file__).resolve().parent.parent


def _source_dir() -> Path:
    # <repo>/data/output  (repo root is the parent of the project dir)
    return _project_dir().parent / "data" / "output"


def _tri_count(asset_path):
    """LOD0 triangle count for a /Game/Detector/<name> static mesh, or None."""
    try:
        sm = unreal.EditorAssetLibrary.load_asset(asset_path)
        if isinstance(sm, unreal.StaticMesh):
            return sm.get_num_triangles(0)
    except Exception:
        pass
    return None


def reimport():
    result = {"imported": [], "skipped": [], "errors": [], "tris": {}}

    if unreal is None:
        result["errors"].append("unreal unavailable — run via UnrealEditor-Cmd -run=pythonscript")
        print("COLLIDERVIS_REIMPORT_RESULT=" + json.dumps(result))
        return result

    src_dir = _source_dir()
    if not src_dir.is_dir():
        result["errors"].append("source dir not found: %s" % src_dir)
        print("COLLIDERVIS_REIMPORT_RESULT=" + json.dumps(result))
        return result

    gltfs = sorted(src_dir.glob("*.gltf"))
    if not gltfs:
        result["errors"].append("no .gltf in %s" % src_dir)
        print("COLLIDERVIS_REIMPORT_RESULT=" + json.dumps(result))
        return result

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    tasks = []
    for src in gltfs:
        name = src.stem
        dest = "%s/%s" % (DEST_PATH, name)
        before = _tri_count(dest)
        result["tris"][name] = {"before": before}
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(src))
        task.set_editor_property("destination_path", DEST_PATH)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("replace_existing_settings", False)  # keep material/scale/Nanite settings
        task.set_editor_property("save", True)
        tasks.append((name, dest, task))

    try:
        tools.import_asset_tasks([t for _, _, t in tasks])
    except Exception as exc:  # noqa: BLE001
        result["errors"].append("import_asset_tasks failed: " + repr(exc))
        traceback.print_exc()

    total_before = total_after = 0
    for name, dest, _task in tasks:
        after = _tri_count(dest)
        result["tris"][name]["after"] = after
        if result["tris"][name]["before"]:
            total_before += result["tris"][name]["before"]
        if after:
            total_after += after
        if unreal.EditorAssetLibrary.does_asset_exist(dest):
            result["imported"].append(name)
        else:
            result["errors"].append("missing after import: %s" % dest)

    result["total_tris_before"] = total_before
    result["total_tris_after"] = total_after

    try:
        unreal.EditorAssetLibrary.save_directory(DEST_PATH, only_if_is_dirty=False)
    except Exception:
        pass

    print("COLLIDERVIS_REIMPORT_RESULT=" + json.dumps(result))
    return result


if __name__ == "__main__":
    reimport()
