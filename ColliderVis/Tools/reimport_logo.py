"""
reimport_logo.py — headless (re)import of the high-res USMCC logo over /Game/UI/Textures/T_USMCCLogo.

TextureTools.import_file refuses to overwrite an existing asset, so this uses an
AssetImportTask with replace_existing=True to swap the texture's source to the
crisp 3600x3600 mark while keeping the SAME asset path (so the splash widget and
the HUD corner watermark — both reference /Game/UI/Textures/T_USMCCLogo by path —
pick it up with no code change).

Run:
    UnrealEditor-Cmd <proj>/ColliderVis/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/ColliderVis/Tools/reimport_logo.py"
"""
import json
import sys
import traceback
from pathlib import Path

try:
    import unreal
except ImportError:
    unreal = None

SRC = "Tools/_assets/USMCCLogo_circles_3600.png"
DEST_PATH = "/Game/UI/Textures"
ASSET_NAME = "T_USMCCLogo"


def run():
    result = {"ok": False, "detail": ""}
    if unreal is None:
        result["detail"] = "unreal module unavailable"
        print("COLLIDERVIS_LOGO_RESULT=" + json.dumps(result))
        return result

    proj = Path(unreal.Paths.project_dir())
    src = proj / SRC
    if not src.is_file():
        result["detail"] = f"source missing: {src}"
        print("COLLIDERVIS_LOGO_RESULT=" + json.dumps(result))
        return result

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(src))
    task.set_editor_property("destination_path", DEST_PATH)
    task.set_editor_property("destination_name", ASSET_NAME)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("replace_existing_settings", False)
    task.set_editor_property("save", True)

    try:
        tools.import_asset_tasks([task])
        obj = f"{DEST_PATH}/{ASSET_NAME}.{ASSET_NAME}"
        tex = unreal.load_object(None, obj)
        if tex:
            result["ok"] = True
            result["detail"] = f"{tex.blueprint_get_size_x()}x{tex.blueprint_get_size_y()}"
        unreal.EditorAssetLibrary.save_asset(f"{DEST_PATH}/{ASSET_NAME}", only_if_is_dirty=False)
    except Exception as exc:  # noqa: BLE001
        result["detail"] = repr(exc)
        traceback.print_exc()

    print("COLLIDERVIS_LOGO_RESULT=" + json.dumps(result))
    return result


run()
