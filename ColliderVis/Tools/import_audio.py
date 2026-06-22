"""
import_audio.py — headless importer for ColliderVis sound effects.

Imports every WAV in Content/Audio/Source/ into USoundWave assets under
/Game/Audio/, mapping each canonical source filename to a stable asset name
that the C++ / Blueprints reference by hardcoded path.

ASSET NAME CONTRACT (matched by C++ LoadObject / TSoftObjectPtr defaults):

    Content/Audio/Source/ui_click.wav      -> /Game/Audio/S_UIClick
    Content/Audio/Source/ui_hover.wav      -> /Game/Audio/S_UIHover
    Content/Audio/Source/splash_whoosh.wav -> /Game/Audio/S_SplashWhoosh   (SplashWidget)
    Content/Audio/Source/ambience_loop.wav -> /Game/Audio/S_AmbienceLoop

Any other *.wav in the Source dir is also imported, named S_<CamelCaseStem>.
Defaults are CC0 — see Content/Audio/CREDITS.md.

How to run
----------
Headless (the orchestrator's path):

    UnrealEditor-Cmd <proj>/ColliderVis/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/ColliderVis/Tools/import_audio.py"

From a live editor's Python console:

    py "<proj>/ColliderVis/Tools/import_audio.py"

To REPLACE a sound: drop a WAV with the same canonical filename into
Content/Audio/Source/ and re-run this script (replace_existing=True rebuilds
the asset in place, preserving the /Game/Audio path so references stay intact).

Design notes
------------
* Idempotent + replace-in-place: re-running re-imports over existing assets at
  the same path, so existing references are never broken.
* Self-reporting: ends by printing a single COLLIDERVIS_AUDIO_RESULT=<json> line
  so an automated agent can parse stdout and react.
"""

import argparse
import json
import re
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

CONTENT_AUDIO = "/Game/Audio"

# Canonical source filename -> /Game/Audio asset name (CONTRACT).
NAME_MAP = {
    "ui_click.wav": "S_UIClick",
    "ui_hover.wav": "S_UIHover",
    "splash_whoosh.wav": "S_SplashWhoosh",
    "ambience_loop.wav": "S_AmbienceLoop",
    "event_sweep.wav": "S_EventSweep",
    "thud.wav": "S_Thud",
    "pad_ping.wav": "S_PadPing",
}


def _project_dir() -> Path:
    """Project root (folder containing ColliderVis.uproject)."""
    if unreal is not None:
        # .../ColliderVis/  (ProjectDir already ends in a separator)
        return Path(unreal.Paths.project_dir())
    # Fallback when run outside the editor: this file is <proj>/Tools/import_audio.py
    return Path(__file__).resolve().parent.parent


def _source_dir() -> Path:
    return _project_dir() / "Content" / "Audio" / "Source"


def _asset_name_for(wav: Path) -> str:
    """Map a wav filename to its /Game/Audio asset name."""
    mapped = NAME_MAP.get(wav.name.lower())
    if mapped:
        return mapped
    # Derive S_<CamelCase> from the stem for any extra wavs.
    parts = re.split(r"[^A-Za-z0-9]+", wav.stem)
    camel = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return "S_" + (camel or "Sound")


def import_audio(args=None):
    result = {"imported": [], "skipped": [], "errors": []}

    if unreal is None:
        msg = "unreal module unavailable — run inside UnrealEditor-Cmd -run=pythonscript"
        result["errors"].append(msg)
        print("COLLIDERVIS_AUDIO_RESULT=" + json.dumps(result))
        return result

    src_dir = _source_dir()
    if not src_dir.is_dir():
        result["errors"].append(f"source dir not found: {src_dir}")
        print("COLLIDERVIS_AUDIO_RESULT=" + json.dumps(result))
        return result

    wavs = sorted(src_dir.glob("*.wav"))
    if not wavs:
        result["errors"].append(f"no .wav files in {src_dir}")
        print("COLLIDERVIS_AUDIO_RESULT=" + json.dumps(result))
        return result

    tools = unreal.AssetToolsHelpers.get_asset_tools()

    tasks = []
    for wav in wavs:
        asset_name = _asset_name_for(wav)
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(wav))
        task.set_editor_property("destination_path", CONTENT_AUDIO)
        task.set_editor_property("destination_name", asset_name)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("save", True)
        tasks.append((wav, asset_name, task))

    try:
        tools.import_asset_tasks([t for _, _, t in tasks])
    except Exception as exc:  # noqa: BLE001
        result["errors"].append("import_asset_tasks failed: " + repr(exc))
        traceback.print_exc()

    # Verify each expected asset now exists at /Game/Audio/<name>.
    for wav, asset_name, _task in tasks:
        obj_path = f"{CONTENT_AUDIO}/{asset_name}.{asset_name}"
        try:
            exists = unreal.EditorAssetLibrary.does_asset_exist(
                f"{CONTENT_AUDIO}/{asset_name}")
        except Exception:  # noqa: BLE001
            exists = False
        if exists:
            result["imported"].append({"source": wav.name, "asset": obj_path})
        else:
            result["errors"].append(
                {"source": wav.name, "expected": obj_path, "status": "not found after import"})

    # The ambient bed must loop forever (the HallAmbience AmbientSound actor plays it
    # on repeat). Re-import resets the SoundWave, so set looping here each time. The
    # one-shot SFX (whoosh / event) are intentionally left non-looping.
    for _wav, asset_name, _t in tasks:
        if asset_name == "S_AmbienceLoop":
            sw = unreal.EditorAssetLibrary.load_asset(f"{CONTENT_AUDIO}/{asset_name}")
            if sw:
                try:
                    sw.set_editor_property("looping", True)
                    result.setdefault("looping_set", []).append(asset_name)
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append("set looping failed: " + repr(exc))

    try:
        unreal.EditorAssetLibrary.save_directory(CONTENT_AUDIO, only_if_is_dirty=False)
    except Exception:  # noqa: BLE001
        pass

    print("COLLIDERVIS_AUDIO_RESULT=" + json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import ColliderVis WAVs to /Game/Audio")
    # Accept/ignore unknown args so it survives UnrealEditor-Cmd's extra argv.
    args, _unknown = parser.parse_known_args(sys.argv[1:])
    import_audio(args)
