"""Headless LOD generation for the heavy non-Nanite detector meshes.
Keeps LOD0 full detail; adds reduced LODs so distant rendering is cheap. Big perf
win on Mac (the meshes total ~4.3M tris with no LODs). Logs via log_warning."""
import unreal

NAMES = ["YokeBarrel", "YokeEndcap", "ECalBarrel", "HCalBarrel", "ECalEndcap", "HCalEndcap"]
PERCENTS = [0.35, 0.12, 0.04]   # LOD1, LOD2, LOD3 triangle retention


def log(m):
    unreal.log_warning("LODGEN: " + str(m))


def make_options():
    opts = unreal.EditorScriptingMeshReductionOptions()
    settings = []
    for p in PERCENTS:
        s = unreal.EditorScriptingMeshReductionSettings()
        s.set_editor_property("percent_triangles", p)
        settings.append(s)
    opts.set_editor_property("reduction_settings", settings)
    opts.set_editor_property("auto_compute_lod_screen_size", True)
    return opts


opts = make_options()
sub = None
try:
    sub = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
except Exception as e:
    log("no StaticMeshEditorSubsystem: " + str(e))

for n in NAMES:
    path = "/Game/Detector/%s" % n
    sm = unreal.load_asset(path)
    if not sm:
        log("%s MISSING" % n)
        continue
    try:
        if sub is not None and hasattr(sub, "set_lods"):
            nl = sub.set_lods(sm, opts)
        else:
            nl = unreal.EditorStaticMeshLibrary.set_lods(sm, opts)
        log("%s -> set_lods returned %s; num_lods now %s" % (n, nl, sm.get_num_lods()))
        unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False)
    except Exception as e:
        log("%s ERR %s" % (n, e))

log("DONE")
