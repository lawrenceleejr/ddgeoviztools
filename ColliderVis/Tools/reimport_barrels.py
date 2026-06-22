"""Headless reimport of the origin-cleaned barrel meshes (replace in place)."""
import unreal
from pathlib import Path

PROJ = Path(unreal.Paths.project_dir())
tools = unreal.AssetToolsHelpers.get_asset_tools()


def task(src, name):
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", str(src))
    t.set_editor_property("destination_path", "/Game/Detector")
    t.set_editor_property("destination_name", name)
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("replace_existing_settings", False)
    t.set_editor_property("save", True)
    return t


tools.import_asset_tasks([
    task(PROJ / "ue5_meshes" / "ECalBarrel.glb", "ECalBarrel"),
    task(PROJ / "ue5_meshes" / "HCalBarrel.glb", "HCalBarrel"),
])
unreal.log_warning("REIMPORT_BARRELS: done")
