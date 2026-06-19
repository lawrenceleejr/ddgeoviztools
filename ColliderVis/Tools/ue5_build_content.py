"""
ue5_build_content.py — one-shot, idempotent UE 5.7 content builder for ColliderVis.

Replaces the manual editor steps 3-7 in README_UE5_IMPORT.md. Given the output of
Tools/blend_to_ue5.py (per-sub-detector *.gltf + manifest.json with lights/cameras), it:

    1. imports the GLTF meshes        -> /Game/Detector/*           (Interchange, Nanite)
    2. forces Nanite on each mesh
    3. creates materials              -> /Game/Materials/*          (M_Track/M_CaloHit/...)
    4. creates Enhanced Input assets  -> /Game/Input/*              (IA_* + IMC_Default/IMC_VR)
    5. creates data assets            -> /Game/Data/*               (DA_*)
    6. creates blueprint stubs        -> /Game/Blueprints, /Game/UI (BP_*, WBP_*)
    7. builds the level               -> /Game/Maps/ColliderVisMain (meshes + Blender lights
                                                                     + managers, set as startup)

How to run
----------
Inside a live UE 5.7 editor (the normal path, e.g. via the mcp-unreal `execute_script` tool):

    import ue5_build_content as b
    b.build({"manifest_dir": "/tmp/ue5_meshes"})

or from the editor Python console / "Execute Python Script":

    py "<proj>/ColliderVis/Tools/ue5_build_content.py" --manifest-dir /tmp/ue5_meshes

Headless is also possible:

    UnrealEditor-Cmd <proj>/ColliderVis/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/ColliderVis/Tools/ue5_build_content.py --manifest-dir /tmp/ue5_meshes"

Design notes
------------
* Idempotent: assets that already exist are skipped (or rebuilt-in-place for the data assets
  and material instances, which must reflect manifest changes). Nothing is deleted, so existing
  references are never broken. Pass rebuild_assets=True to force a clean re-import of meshes.
* Robust to UE Python name mangling: properties are set via `_set_prop(obj, value, *candidates)`
  which loosely matches candidate snake_case names against the object's real attributes.
* Self-reporting: every stage is wrapped in try/except; the run ends by printing a single
  `COLLIDERVIS_BUILD_RESULT=<json>` line so an automated agent can parse stdout and react.
* The asset PATHS below are CONTRACTS: the C++ loads them by hardcoded path
  (e.g. TrackActor.cpp -> /Game/Materials/M_Track, ColliderVisHUD.cpp -> /Game/UI/WBP_Options).
  Do not rename them without updating the C++.
"""

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

try:
    import unreal
except ImportError:
    unreal = None


# ─────────────────────────────────────────────────────────────────────────────
# Content paths (CONTRACTS — matched by C++ LoadObject/LoadClass calls)
# ─────────────────────────────────────────────────────────────────────────────
CONTENT_DETECTOR  = "/Game/Detector"
CONTENT_MATERIALS = "/Game/Materials"
CONTENT_MIC       = "/Game/Materials/Instances"
CONTENT_INPUT     = "/Game/Input"
CONTENT_DATA      = "/Game/Data"
CONTENT_BP        = "/Game/Blueprints"
CONTENT_UI        = "/Game/UI"
MAP_PATH          = "/Game/Maps/ColliderVisMain"

# Blender (Z-up, metres, right-handed) -> UE (Z-up, centimetres, left-handed).
M_TO_CM = 100.0
# Flip Y for the handedness change. This is the single most likely value to need
# calibration against the imported (export_yup) geometry — verify with a screenshot
# and flip if the lights end up mirrored. See blend_to_ue5.py module docstring.
FLIP_Y = True

# Photometric approximations (Blender radiometric watts -> UE photometric units).
# Exact Cycles<->Lumen matching is impossible across renderers; these are tunable
# starting points, refined visually via the mcp-unreal capture_viewport loop.
LUMENS_PER_WATT = 120.0   # AREA / POINT / SPOT  (Blender W -> UE lumens)
LUX_PER_WM2     = 120.0   # SUN                  (Blender W/m^2 -> UE lux)

# Number-row FKey names (UE EKeys use spelled-out names).
_NUM_KEYS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
             6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}


# ─────────────────────────────────────────────────────────────────────────────
# Logging + structured report
# ─────────────────────────────────────────────────────────────────────────────
def _log(msg):
    if unreal:
        unreal.log("[ColliderVisBuild] " + str(msg))
    else:
        print("[ColliderVisBuild] " + str(msg))


def _warn(msg):
    if unreal:
        unreal.log_warning("[ColliderVisBuild] " + str(msg))
    else:
        print("WARNING [ColliderVisBuild] " + str(msg), file=sys.stderr)


def _err(msg):
    if unreal:
        unreal.log_error("[ColliderVisBuild] " + str(msg))
    else:
        print("ERROR [ColliderVisBuild] " + str(msg), file=sys.stderr)


class BuildReport:
    """Accumulates per-stage status and prints a parseable result sentinel."""

    def __init__(self):
        self.stages = []
        self.todos = []

    def stage(self, name):
        entry = {"stage": name, "status": "ok", "detail": "",
                 "created": [], "skipped": []}
        self.stages.append(entry)
        return _StageCtx(name, entry)

    def todo(self, msg):
        self.todos.append(msg)
        _warn("MANUAL TODO: " + msg)

    def finish(self):
        ok = sum(1 for s in self.stages if s["status"] == "ok")
        warn = sum(1 for s in self.stages if s["status"] == "warn")
        fail = sum(1 for s in self.stages if s["status"] == "fail")
        result = {
            "ok": fail == 0,
            "summary": {"stages": len(self.stages), "ok": ok, "warn": warn, "fail": fail},
            "stages": self.stages,
            "manual_todos": self.todos,
        }
        _log("──────────── build complete ────────────")
        for s in self.stages:
            _log("  [{status:>4}] {stage}  (+{c} ~{k}) {detail}".format(
                status=s["status"], stage=s["stage"],
                c=len(s["created"]), k=len(s["skipped"]),
                detail=("- " + s["detail"]) if s["detail"] else ""))
        if self.todos:
            _log("  manual TODOs: %d (see warnings above)" % len(self.todos))
        # Single-line sentinel for automated parsing.
        _log("COLLIDERVIS_BUILD_RESULT=" + json.dumps(result))
        return result


class _StageCtx:
    def __init__(self, name, entry):
        self.name = name
        self.entry = entry

    def __enter__(self):
        _log("=== %s ===" % self.name)
        return self.entry

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.entry["status"] = "fail"
            self.entry["detail"] = "%s: %s" % (exc_type.__name__, exc)
            _err("[%s] FAILED: %s" % (self.name, exc))
            _err(traceback.format_exc())
            return True  # swallow — one stage failing must not abort the build
        if self.entry["status"] == "ok":
            _log("[%s] OK (created %d, skipped %d)"
                 % (self.name, len(self.entry["created"]), len(self.entry["skipped"])))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Generic UE helpers (tolerant of version-to-version naming differences)
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_attr(obj, *candidates):
    """First real attribute name on obj matching a candidate (loose, ignores '_'/case)."""
    have = set(dir(obj))
    for c in candidates:
        if c in have:
            return c
    norm = {a.replace("_", "").lower(): a for a in have}
    for c in candidates:
        key = c.replace("_", "").lower()
        if key in norm:
            return norm[key]
    return None


def _set_prop(obj, value, *candidates):
    """set_editor_property tolerant of name mangling. Returns the name used or None."""
    name = _resolve_attr(obj, *candidates)
    if name is None:
        _warn("property %s not found on %s" % (candidates, type(obj).__name__))
        return None
    obj.set_editor_property(name, value)
    return name


def _enum(enum_cls, *candidates):
    """First existing member of an unreal enum, else None."""
    for c in candidates:
        if hasattr(enum_cls, c):
            return getattr(enum_cls, c)
    return None


def _make_struct(*names):
    for n in names:
        if hasattr(unreal, n):
            try:
                return getattr(unreal, n)()
            except Exception:
                pass
    raise AttributeError("no struct constructor among %s" % (names,))


def _exists(path):
    return unreal.EditorAssetLibrary.does_asset_exist(path)


def _load(path):
    return unreal.EditorAssetLibrary.load_asset(path)


def _save(asset):
    unreal.EditorAssetLibrary.save_loaded_asset(asset)


def _tools():
    return unreal.AssetToolsHelpers.get_asset_tools()


def _create_asset(name, path, ucls, factory):
    full = "%s/%s" % (path, name)
    if _exists(full):
        return _load(full)
    return _tools().create_asset(name, path, ucls, factory)


def _lc(seq, default=(0.5, 0.5, 0.5, 1.0)):
    """Coerce a [r,g,b(,a)] list to an unreal.LinearColor."""
    vals = list(seq) if seq else list(default)
    while len(vals) < 4:
        vals.append(1.0)
    return unreal.LinearColor(float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — import GLTF meshes (Interchange)
# ─────────────────────────────────────────────────────────────────────────────
def stage_import_gltf(report, export_dir, manifest, rebuild=False):
    with report.stage("import_gltf") as st:
        tasks = []
        for entry in manifest["sub_detectors"]:
            name = entry["name"]
            src = export_dir / entry["gltf_file"]
            dest = "%s/%s" % (CONTENT_DETECTOR, name)
            if not src.exists():
                _warn("missing gltf: %s" % src)
                st["skipped"].append(name)
                continue
            if _exists(dest) and not rebuild:
                st["skipped"].append(name)
                continue
            task = unreal.AssetImportTask()
            task.set_editor_property("filename", str(src))
            task.set_editor_property("destination_path", CONTENT_DETECTOR)
            task.set_editor_property("automated", True)
            task.set_editor_property("replace_existing", True)
            task.set_editor_property("save", True)
            tasks.append((entry, task))

        if tasks:
            # Default Interchange pipeline imports glTF normals; Nanite is forced in stage 2.
            _tools().import_asset_tasks([t for _, t in tasks])
            for entry, task in tasks:
                _normalize_import(task, entry["name"], st)


def _normalize_import(task, target_name, st):
    """Interchange names assets after the glTF node; rename to the sub-detector name."""
    target = "%s/%s" % (CONTENT_DETECTOR, target_name)
    paths = []
    try:
        paths = list(task.get_editor_property("imported_object_paths"))
    except Exception:
        try:
            paths = [o.get_path_name() for o in task.get_objects()]
        except Exception:
            paths = []
    sm_pkgs = []
    for p in paths:
        pkg = p.split(".")[0]
        obj = _load(pkg)
        if isinstance(obj, unreal.StaticMesh):
            sm_pkgs.append(pkg)
    if not sm_pkgs:
        # Either import failed or asset already at target; record as created if present.
        st["created" if _exists(target) else "skipped"].append(target_name)
        return
    primary = sm_pkgs[0]
    if primary != target:
        if _exists(target):
            unreal.EditorAssetLibrary.delete_asset(target)
        unreal.EditorAssetLibrary.rename_asset(primary, target)
    st["created"].append(target_name)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — force Nanite
# ─────────────────────────────────────────────────────────────────────────────
def stage_nanite(report, manifest):
    with report.stage("nanite") as st:
        for entry in manifest["sub_detectors"]:
            name = entry["name"]
            sm = _load("%s/%s" % (CONTENT_DETECTOR, name))
            if isinstance(sm, unreal.StaticMesh):
                try:
                    sm.set_editor_property("nanite_settings",
                                           unreal.MeshNaniteSettings(enabled=True))
                    _save(sm)
                    st["created"].append(name)
                except Exception as e:
                    _warn("nanite %s: %s" % (name, e))
                    st["status"] = "warn"
            else:
                st["skipped"].append(name)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — materials + per-sub-detector material instances
# ─────────────────────────────────────────────────────────────────────────────
def _mel():
    return unreal.MaterialEditingLibrary


def _new_material(name):
    return _create_asset(name, CONTENT_MATERIALS, unreal.Material, unreal.MaterialFactoryNew())


def _expr(mat, cls, x=0, y=0):
    return _mel().create_material_expression(mat, cls, x, y)


def _mp(name):
    return _enum(unreal.MaterialProperty, name)


def _set_blend(mat, blend, shading=None):
    b = _enum(unreal.BlendMode, blend)
    if b is not None:
        _set_prop(mat, b, "blend_mode")
    if shading:
        s = _enum(unreal.MaterialShadingModel, shading)
        if s is not None:
            _set_prop(mat, s, "shading_model")


def _make_m_track():
    mat = _new_material("M_Track")
    col = _expr(mat, unreal.MaterialExpressionVectorParameter, -600, -100)
    col.set_editor_property("parameter_name", "TrackColor")
    col.set_editor_property("default_value", unreal.LinearColor(1.0, 0.4, 0.1, 1.0))
    emi = _expr(mat, unreal.MaterialExpressionScalarParameter, -600, 150)
    emi.set_editor_property("parameter_name", "EmissiveIntensity")
    emi.set_editor_property("default_value", 1.0)
    mul = _expr(mat, unreal.MaterialExpressionMultiply, -300, 100)
    _mel().connect_material_expression(col, "", mul, "A")
    _mel().connect_material_expression(emi, "", mul, "B")
    _mel().connect_material_property(col, "", _mp("MP_BASE_COLOR"))
    _mel().connect_material_property(mul, "", _mp("MP_EMISSIVE_COLOR"))
    rough = _expr(mat, unreal.MaterialExpressionConstant, -300, 320)
    rough.set_editor_property("r", 0.3)
    metal = _expr(mat, unreal.MaterialExpressionConstant, -300, 420)
    metal.set_editor_property("r", 0.6)
    _mel().connect_material_property(rough, "", _mp("MP_ROUGHNESS"))
    _mel().connect_material_property(metal, "", _mp("MP_METALLIC"))
    _set_blend(mat, "BLEND_OPAQUE", "MSM_DEFAULT_LIT")
    _mel().recompile_material(mat)
    _save(mat)


def _make_m_calohit():
    mat = _new_material("M_CaloHit")
    _set_blend(mat, "BLEND_TRANSLUCENT", "MSM_UNLIT")
    energy = _expr(mat, unreal.MaterialExpressionScalarParameter, -700, 0)
    energy.set_editor_property("parameter_name", "Energy")
    try:
        energy.set_editor_property("use_custom_primitive_data", True)
        energy.set_editor_property("primitive_data_index", 0)
    except Exception as e:
        _warn("M_CaloHit custom-primitive-data flag unavailable (%s); "
              "wire CPD[0]->Energy in the editor." % e)
    cold = _expr(mat, unreal.MaterialExpressionConstant3Vector, -500, -160)
    cold.set_editor_property("constant", unreal.LinearColor(0.0, 0.1, 0.5, 1.0))
    hot = _expr(mat, unreal.MaterialExpressionConstant3Vector, -500, 160)
    hot.set_editor_property("constant", unreal.LinearColor(1.5, 1.2, 0.8, 1.0))
    lerp = _expr(mat, unreal.MaterialExpressionLinearInterpolate, -250, 0)
    _mel().connect_material_expression(cold, "", lerp, "A")
    _mel().connect_material_expression(hot, "", lerp, "B")
    _mel().connect_material_expression(energy, "", lerp, "Alpha")
    _mel().connect_material_property(lerp, "", _mp("MP_EMISSIVE_COLOR"))
    _mel().recompile_material(mat)
    _save(mat)


def _make_m_mcparticle():
    mat = _new_material("M_MCParticle")
    _set_blend(mat, "BLEND_TRANSLUCENT", "MSM_UNLIT")
    emi = _expr(mat, unreal.MaterialExpressionConstant3Vector, -400, 0)
    emi.set_editor_property("constant", unreal.LinearColor(0.6, 0.6, 1.5, 1.0))
    _mel().connect_material_property(emi, "", _mp("MP_EMISSIVE_COLOR"))
    op = _expr(mat, unreal.MaterialExpressionConstant, -400, 220)
    op.set_editor_property("r", 0.7)
    _mel().connect_material_property(op, "", _mp("MP_OPACITY"))
    _mel().recompile_material(mat)
    _save(mat)


def _make_m_detector():
    mat = _new_material("M_DetectorGeometry")
    bc = _expr(mat, unreal.MaterialExpressionVectorParameter, -500, -120)
    bc.set_editor_property("parameter_name", "BaseColor")
    bc.set_editor_property("default_value", unreal.LinearColor(0.5, 0.5, 0.5, 1.0))
    me = _expr(mat, unreal.MaterialExpressionScalarParameter, -500, 100)
    me.set_editor_property("parameter_name", "Metallic")
    me.set_editor_property("default_value", 0.5)
    ro = _expr(mat, unreal.MaterialExpressionScalarParameter, -500, 250)
    ro.set_editor_property("parameter_name", "Roughness")
    ro.set_editor_property("default_value", 0.5)
    _mel().connect_material_property(bc, "", _mp("MP_BASE_COLOR"))
    _mel().connect_material_property(me, "", _mp("MP_METALLIC"))
    _mel().connect_material_property(ro, "", _mp("MP_ROUGHNESS"))
    _mel().recompile_material(mat)
    _save(mat)
    return mat


def stage_materials(report, manifest):
    with report.stage("materials") as st:
        for fn, nm in ((_make_m_track, "M_Track"),
                       (_make_m_calohit, "M_CaloHit"),
                       (_make_m_mcparticle, "M_MCParticle")):
            try:
                fn()
                st["created"].append(nm)
            except Exception as e:
                _warn("%s: %s" % (nm, e))
                st["status"] = "warn"

        base = _make_m_detector()
        st["created"].append("M_DetectorGeometry")

        for entry in manifest["sub_detectors"]:
            name = entry["name"]
            try:
                mic = _create_asset("MI_%s" % name, CONTENT_MIC,
                                    unreal.MaterialInstanceConstant,
                                    unreal.MaterialInstanceConstantFactoryNew())
                mic.set_editor_property("parent", base)
                _mel().set_material_instance_vector_parameter_value(
                    mic, "BaseColor", _lc(entry.get("base_color")))
                _mel().set_material_instance_scalar_parameter_value(
                    mic, "Metallic", float(entry.get("metallic", 0.5)))
                _mel().set_material_instance_scalar_parameter_value(
                    mic, "Roughness", float(entry.get("roughness", 0.5)))
                _save(mic)
                sm = _load("%s/%s" % (CONTENT_DETECTOR, name))
                if isinstance(sm, unreal.StaticMesh):
                    sm.set_material(0, mic)
                    _save(sm)
                st["created"].append("MI_%s" % name)
            except Exception as e:
                _warn("MI_%s: %s" % (name, e))
                st["status"] = "warn"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Enhanced Input
# ─────────────────────────────────────────────────────────────────────────────
def _value_type(kind):
    vt = unreal.InputActionValueType
    table = {"axis1d": ("AXIS1D", "Axis1D"),
             "axis2d": ("AXIS2D", "Axis2D"),
             "bool":   ("BOOLEAN", "Boolean", "Digital")}
    return _enum(vt, *table[kind])


def _make_input_action(name, kind):
    full = "%s/%s" % (CONTENT_INPUT, name)
    if _exists(full):
        a = _load(full)
    else:
        try:
            a = _tools().create_asset(name, CONTENT_INPUT, unreal.InputAction,
                                      unreal.InputActionFactory())
        except Exception:
            a = _tools().create_asset(name, CONTENT_INPUT, unreal.InputAction, None)
    vt = _value_type(kind)
    if vt is not None:
        _set_prop(a, vt, "value_type")
    _save(a)
    return a


def _key(name):
    """Build an FKey from an EKeys name, validating it. Returns None if unknown."""
    if not name:
        return None
    k = None
    try:
        k = unreal.Key(name)
    except Exception:
        try:
            k = unreal.Key()
            _set_prop(k, unreal.Name(name), "key_name")
        except Exception:
            return None
    try:
        if hasattr(k, "is_valid") and not k.is_valid():
            _warn("unknown FKey '%s' — skipped" % name)
            return None
    except Exception:
        pass
    return k


def _mod_negate():
    return unreal.InputModifierNegate()


def _mod_swizzle():
    s = unreal.InputModifierSwizzleAxis()
    order = _enum(unreal.InputAxisSwizzle, "YXZ")
    if order is not None:
        _set_prop(s, order, "order")
    return s


def _mod_scalar(v):
    s = unreal.InputModifierScalar()
    _set_prop(s, unreal.Vector(float(v), float(v), float(v)), "scalar")
    return s


def _add_mapping(imc, action, key, modifiers=None, triggers=None):
    if action is None or key is None:
        return False
    try:
        m = imc.map_key(action, key)
        if modifiers:
            if _set_prop(m, modifiers, "modifiers") is None:
                try:
                    m.modifiers = modifiers
                except Exception:
                    pass
        if triggers:
            if _set_prop(m, triggers, "triggers") is None:
                try:
                    m.triggers = triggers
                except Exception:
                    pass
        return True
    except Exception as e:
        _warn("map_key failed (%s): %s" % (key, e))
        return False


def _make_imc(name):
    full = "%s/%s" % (CONTENT_INPUT, name)
    if _exists(full):
        imc = _load(full)
    else:
        try:
            imc = _tools().create_asset(name, CONTENT_INPUT, unreal.InputMappingContext,
                                        unreal.InputMappingContextFactory())
        except Exception:
            imc = _tools().create_asset(name, CONTENT_INPUT, unreal.InputMappingContext, None)
    # Reset for idempotency (best effort).
    try:
        imc.set_editor_property("mappings", [])
    except Exception:
        pass
    return imc


def stage_input(report):
    """Returns {asset_name: InputAction} for downstream use."""
    actions = {}
    with report.stage("input") as st:
        spec = {
            "IA_Move": "axis2d", "IA_Look": "axis2d", "IA_Jump": "bool",
            "IA_SwitchMode": "bool", "IA_Zoom": "bool", "IA_NextEvent": "bool",
            "IA_OpenMenu": "bool", "IA_ToggleDetectorMenu": "bool",
            "IA_DetectorKey": "axis1d",
        }
        for nm, kind in spec.items():
            try:
                actions[nm] = _make_input_action(nm, kind)
                st["created"].append(nm)
            except Exception as e:
                _warn("%s: %s" % (nm, e))
                st["status"] = "warn"

        # IMC_Default (desktop) — fully built incl. modifiers.
        try:
            imc = _make_imc("IMC_Default")
            _add_mapping(imc, actions.get("IA_Move"), _key("W"))
            _add_mapping(imc, actions.get("IA_Move"), _key("S"), [_mod_negate()])
            _add_mapping(imc, actions.get("IA_Move"), _key("A"), [_mod_swizzle(), _mod_negate()])
            _add_mapping(imc, actions.get("IA_Move"), _key("D"), [_mod_swizzle()])
            _add_mapping(imc, actions.get("IA_Look"), _key("Mouse2D"))
            _add_mapping(imc, actions.get("IA_Jump"), _key("SpaceBar"))
            _add_mapping(imc, actions.get("IA_SwitchMode"), _key("Tab"))
            # Hold Right Mouse Button to dynamically zoom the camera in for detail.
            _add_mapping(imc, actions.get("IA_Zoom"), _key("RightMouseButton"))
            _add_mapping(imc, actions.get("IA_NextEvent"), _key("N"))
            _add_mapping(imc, actions.get("IA_OpenMenu"), _key("Escape"))
            _add_mapping(imc, actions.get("IA_ToggleDetectorMenu"), _key("V"))
            for i in range(1, 10):
                _add_mapping(imc, actions.get("IA_DetectorKey"),
                             _key(_NUM_KEYS[i]), [_mod_scalar(i)])
            _save(imc)
            st["created"].append("IMC_Default")
        except Exception as e:
            _warn("IMC_Default: %s" % e)
            st["status"] = "warn"

        # IMC_VR (best effort — XR FKey names vary by plugin; invalid keys are skipped).
        try:
            vr = _make_imc("IMC_VR")
            mapped = 0
            mapped += _add_mapping(vr, actions.get("IA_Move"),
                                   _key("MotionController_Left_Thumbstick_X"))
            mapped += _add_mapping(vr, actions.get("IA_Move"),
                                   _key("MotionController_Left_Thumbstick_Y"), [_mod_swizzle()])
            mapped += _add_mapping(vr, actions.get("IA_Look"),
                                   _key("MotionController_Right_Thumbstick_X"))
            mapped += _add_mapping(vr, actions.get("IA_NextEvent"),
                                   _key("OculusTouch_Right_A_Click"))
            _save(vr)
            st["created"].append("IMC_VR")
            if mapped < 4:
                report.todo("IMC_VR: some XR controller bindings (grip/trigger thresholds, "
                            "and any skipped thumbstick/A keys) need wiring manually — the "
                            "exact OpenXR FKey names depend on your installed VR plugins "
                            "(see UE5_SETUP.md §3c).")
        except Exception as e:
            _warn("IMC_VR: %s" % e)
            report.todo("IMC_VR could not be built automatically; create it manually per "
                        "UE5_SETUP.md §3c.")
    return actions


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 — data assets
# ─────────────────────────────────────────────────────────────────────────────
def _data_asset(name, ucls):
    full = "%s/%s" % (CONTENT_DATA, name)
    if _exists(full):
        return _load(full)
    try:
        return _tools().create_asset(name, CONTENT_DATA, ucls, unreal.DataAssetFactory())
    except Exception:
        return _tools().create_asset(name, CONTENT_DATA, ucls, None)


def stage_data_assets(report, manifest, edm4hep_script):
    """Returns (event_cfg, vis_cfg) assets for downstream blueprint/level wiring."""
    ev = vis = None
    with report.stage("data_assets") as st:
        # DA_EventDisplayConfig
        ev = _data_asset("DA_EventDisplayConfig", unreal.EventDisplayConfig)
        _set_prop(ev, "python3", "python_executable")
        if edm4hep_script:
            _set_prop(ev, str(edm4hep_script),
                      "edm4_hep_script_path", "edm4hep_script_path", "edmhep_script_path")
        _set_prop(ev, 2.0, "track_tube_radius")
        _set_prop(ev, 50.0, "energy_emissive_scale")
        _set_prop(ev, 5.0, "calo_hit_base_size")
        _set_prop(ev, 0.1, "world_scale")
        _set_prop(ev, [unreal.Name("ECalBarrelHits"), unreal.Name("HCalBarrelHits")],
                  "enabled_calo_collections")
        _save(ev)
        st["created"].append("DA_EventDisplayConfig")

        # DA_DetectorVisibility
        vis = _data_asset("DA_DetectorVisibility", unreal.DetectorVisibilityConfig)
        rows = []
        for i, entry in enumerate(manifest["sub_detectors"], start=1):
            e = _make_struct("SubDetectorEntry", "FSubDetectorEntry")
            _set_prop(e, unreal.Name(entry["name"]), "name")
            _set_prop(e, True, "b_visible_by_default")
            _set_prop(e, _lc(entry.get("base_color"), (1, 1, 1, 1)), "label_color")
            _set_prop(e, i if i <= 9 else 0, "hotkey_slot")
            tags = entry.get("actor_tags") or [entry["name"]]
            _set_prop(e, [unreal.Name(t) for t in tags], "actor_tags")
            rows.append(e)
        _set_prop(vis, rows, "sub_detectors")
        _save(vis)
        st["created"].append("DA_DetectorVisibility")

        # DA_DetectorGeometryManifest
        man = _data_asset("DA_DetectorGeometryManifest", unreal.DetectorGeometryManifest)
        ms = []
        for entry in manifest["sub_detectors"]:
            m = _make_struct("SubDetectorManifestEntry", "FSubDetectorManifestEntry")
            _set_prop(m, entry["name"], "name")
            _set_prop(m, entry.get("gltf_file", ""), "gltf_file")
            _set_prop(m, _lc(entry.get("base_color")), "base_color")
            _set_prop(m, float(entry.get("metallic", 0.5)), "metallic")
            _set_prop(m, float(entry.get("roughness", 0.5)), "roughness")
            tags = entry.get("actor_tags") or [entry["name"]]
            _set_prop(m, [unreal.Name(t) for t in tags], "actor_tags")
            ms.append(m)
        _set_prop(man, ms, "sub_detectors")
        _save(man)
        st["created"].append("DA_DetectorGeometryManifest")
    return ev, vis


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6 — blueprint + widget stubs
# ─────────────────────────────────────────────────────────────────────────────
def _generated_class(bp):
    for getter in ("generated_class", "get_blueprint_generated_class"):
        if hasattr(bp, getter):
            try:
                cls = getattr(bp, getter)()
                if cls is not None:
                    return cls
            except Exception:
                pass
    try:
        return bp.get_editor_property("generated_class")
    except Exception:
        return None


def _compile_bp(bp):
    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    except Exception as e:
        _warn("compile_blueprint: %s" % e)


def _make_bp(name, parent, path=CONTENT_BP):
    full = "%s/%s" % (path, name)
    if _exists(full):
        return _load(full)
    f = unreal.BlueprintFactory()
    _set_prop(f, parent, "parent_class")
    return _tools().create_asset(name, path, None, f)


def _make_wbp(name, parent):
    full = "%s/%s" % (CONTENT_UI, name)
    if _exists(full):
        return _load(full)
    f = unreal.WidgetBlueprintFactory()
    _set_prop(f, parent, "parent_class")
    return _tools().create_asset(name, CONTENT_UI, None, f)


def stage_blueprints(report, event_cfg):
    with report.stage("blueprints") as st:
        try:
            bp = _make_bp("BP_EventDisplayManager", unreal.EventDisplayManager)
            cls = _generated_class(bp)
            if cls is not None and event_cfg is not None:
                cdo = unreal.get_default_object(cls)
                if cdo is not None:
                    _set_prop(cdo, event_cfg, "config")
            _compile_bp(bp)
            _save(bp)
            st["created"].append("BP_EventDisplayManager")
        except Exception as e:
            _warn("BP_EventDisplayManager: %s" % e)
            st["status"] = "warn"

        for nm, parent in (("BP_CineCamera", "ColliderVisCineCameraActor"),
                           ("BP_ColliderVisCharacter", "ColliderVisCharacter")):
            pcls = getattr(unreal, parent, None)
            if pcls is None:
                continue
            try:
                bp = _make_bp(nm, pcls)
                _compile_bp(bp)
                _save(bp)
                st["created"].append(nm)
            except Exception as e:
                _warn("%s: %s" % (nm, e))
                st["status"] = "warn"

        # The third-person character uses the UE Mannequin Quinn (an example model).
        # The C++ AColliderVisCharacter auto-binds it from /Game/Characters/Mannequins/
        # when that content exists. Flag if the Third Person feature pack is missing.
        if not _exists("/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple"):
            report.todo("Add the example character model: Editor → Add (Content Browser) → "
                        "'Add Feature or Content Pack' → Blueprint/C++ → 'Third Person', then "
                        "recompile. This imports /Game/Characters/Mannequins/* which the "
                        "character auto-binds (SKM_Quinn_Simple + ABP_Quinn). Until then the "
                        "character is playable but invisible.")

        # Widget stubs (parents must resolve so C++ LoadClass succeeds; visual layout manual).
        try:
            _make_wbp("WBP_Options", unreal.ColliderVisOptionsWidget)
            _make_wbp("WBP_DetectorRow", unreal.UserWidget)
            st["created"] += ["WBP_Options", "WBP_DetectorRow"]
        except Exception as e:
            _warn("widget stubs: %s" % e)
            st["status"] = "warn"
        report.todo("Build the WBP_Options / WBP_DetectorRow visual layout + button-event "
                    "wiring in the UMG designer (UE5_SETUP.md §7). The C++ HUD only needs the "
                    "assets to exist at /Game/UI/WBP_Options; logic lives in C++.")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 7 — level (meshes + lights + managers) and startup map
# ─────────────────────────────────────────────────────────────────────────────
def _b2u_location(loc):
    x, y, z = loc[0], loc[1], loc[2]
    return unreal.Vector(x * M_TO_CM, (-y if FLIP_Y else y) * M_TO_CM, z * M_TO_CM)


def _b2u_direction(d):
    x, y, z = d[0], d[1], d[2]
    return unreal.Vector(x, -y if FLIP_Y else y, z)


def _rot_from_direction(d):
    try:
        return unreal.MathLibrary.make_rot_from_x(_b2u_direction(d))
    except Exception:
        return unreal.Rotator(0.0, 0.0, 0.0)


def _light_component(actor):
    for attr in ("rect_light_component", "point_light_component",
                 "spot_light_component", "directional_light_component",
                 "light_component"):
        if hasattr(actor, attr):
            c = getattr(actor, attr)
            if c is not None:
                return c
    for cls_name in ("RectLightComponent", "PointLightComponent",
                     "SpotLightComponent", "DirectionalLightComponent",
                     "LightComponent"):
        cls = getattr(unreal, cls_name, None)
        if cls is not None:
            try:
                c = actor.get_component_by_class(cls)
                if c is not None:
                    return c
            except Exception:
                pass
    return None


def _configure_light(comp, L):
    t = L["type"]
    temp = L.get("temperature_k")
    if temp:
        _set_prop(comp, True, "use_temperature")
        _set_prop(comp, float(temp), "temperature")
    col = L.get("color")
    if col and len(col) >= 3:
        try:
            comp.set_light_color(unreal.LinearColor(col[0], col[1], col[2], 1.0))
        except Exception:
            _set_prop(comp, _lc(col).to_color(True), "light_color")

    energy = float(L.get("energy", 0.0))
    if t == "SUN":
        _set_prop(comp, energy * LUX_PER_WM2, "intensity")
    else:
        units = _enum(unreal.LightUnits, "LUMENS", "Lumens")
        if units is not None:
            _set_prop(comp, units, "intensity_units")
        _set_prop(comp, energy * LUMENS_PER_WATT, "intensity")
        _set_prop(comp, 5000.0, "attenuation_radius")

    if t == "AREA":
        _set_prop(comp, float(L.get("size", 1.0)) * M_TO_CM, "source_width")
        _set_prop(comp, float(L.get("size_y", L.get("size", 1.0))) * M_TO_CM, "source_height")
    if t == "SPOT":
        outer = math.degrees(float(L.get("spot_size_rad", 1.0))) / 2.0
        inner = outer * (1.0 - float(L.get("spot_blend", 0.0)))
        _set_prop(comp, outer, "outer_cone_angle")
        _set_prop(comp, inner, "inner_cone_angle")


_LIGHT_CLASS = {"POINT": "PointLight", "SPOT": "SpotLight",
                "AREA": "RectLight", "SUN": "DirectionalLight"}


def _spawn_lights(manifest, eas, existing_labels, st):
    for L in manifest.get("lights", []):
        label = "Light_%s" % L["name"]
        if label in existing_labels:
            st["skipped"].append(label)
            continue
        cls = getattr(unreal, _LIGHT_CLASS.get(L.get("type"), ""), None)
        if cls is None:
            st["skipped"].append(label)
            continue
        try:
            loc = _b2u_location(L["location_m"])
            rot = _rot_from_direction(L.get("direction") or [0.0, 0.0, -1.0])
            actor = eas.spawn_actor_from_class(cls, loc, rot)
            actor.set_actor_label(label)
            comp = _light_component(actor)
            if comp is not None:
                _configure_light(comp, L)
            st["created"].append(label)
        except Exception as e:
            _warn("light %s: %s" % (label, e))
            st["status"] = "warn"


def _set_world_gamemode():
    """Best effort — DefaultGame.ini already sets the global default game mode."""
    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        ws = None
        try:
            ws = world.get_world_settings()
        except Exception:
            for a in unreal.get_editor_subsystem(
                    unreal.EditorActorSubsystem).get_all_level_actors():
                if isinstance(a, unreal.WorldSettings):
                    ws = a
                    break
        gm = getattr(unreal, "ColliderVisGameMode", None)
        if ws is not None and gm is not None:
            _set_prop(ws, gm, "default_game_mode")
    except Exception as e:
        _warn("gamemode override (non-fatal, DefaultGame.ini covers it): %s" % e)


def _set_startup_map(report):
    """Append EditorStartupMap / GameDefaultMap to DefaultEngine.ini (idempotent)."""
    try:
        cfg_dir = Path(unreal.Paths.project_config_dir())
    except Exception:
        cfg_dir = Path(__file__).resolve().parent.parent / "Config"
    ini = cfg_dir / "DefaultEngine.ini"
    map_ref = "%s.%s" % (MAP_PATH, MAP_PATH.rsplit("/", 1)[-1])
    try:
        text = ini.read_text() if ini.exists() else ""
        if ("EditorStartupMap=" + map_ref) in text:
            return
        block = ("\n[/Script/EngineSettings.GameMapsSettings]\n"
                 "EditorStartupMap=%s\n"
                 "GameDefaultMap=%s\n" % (map_ref, map_ref))
        ini.write_text(text + block)
        _log("startup map written to %s" % ini)
    except Exception as e:
        _warn("could not set startup map: %s" % e)
        report.todo("Set Project Settings > Maps & Modes > Editor Startup Map + Game Default "
                    "Map to /Game/Maps/ColliderVisMain manually.")


def stage_level(report, manifest, event_cfg, vis_cfg):
    with report.stage("level") as st:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

        if _exists(MAP_PATH):
            les.load_level(MAP_PATH)
        else:
            les.new_level(MAP_PATH)

        _set_world_gamemode()

        existing = set()
        for a in eas.get_all_level_actors():
            try:
                existing.add(a.get_actor_label())
            except Exception:
                pass

        # Detector meshes at origin, Static, no collision, tagged.
        for entry in manifest["sub_detectors"]:
            name = entry["name"]
            label = "Detector_%s" % name
            if label in existing:
                st["skipped"].append(label)
                continue
            sm = _load("%s/%s" % (CONTENT_DETECTOR, name))
            if not isinstance(sm, unreal.StaticMesh):
                st["skipped"].append(label)
                continue
            try:
                actor = eas.spawn_actor_from_object(sm, unreal.Vector(0, 0, 0),
                                                    unreal.Rotator(0, 0, 0))
                comp = actor.static_mesh_component
                comp.set_mobility(unreal.ComponentMobility.STATIC)
                comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
                actor.set_actor_label(label)
                actor.tags = list(entry.get("actor_tags") or [name])
                st["created"].append(label)
            except Exception as e:
                _warn("mesh actor %s: %s" % (label, e))
                st["status"] = "warn"

        # Blender light rig.
        _spawn_lights(manifest, eas, existing, st)

        # Managers.
        try:
            cls = unreal.EditorAssetLibrary.load_blueprint_class(
                "%s/BP_EventDisplayManager" % CONTENT_BP)
            if cls is not None:
                edm = eas.spawn_actor_from_class(cls, unreal.Vector(0, 0, 0),
                                                 unreal.Rotator(0, 0, 0))
                if edm is not None and event_cfg is not None:
                    _set_prop(edm, event_cfg, "config")
                    edm.set_actor_label("EventDisplayManager")
                st["created"].append("EventDisplayManager")
        except Exception as e:
            _warn("EventDisplayManager: %s" % e)
            st["status"] = "warn"

        try:
            vmgr = eas.spawn_actor_from_class(unreal.DetectorVisibilityManager,
                                              unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
            if vmgr is not None and vis_cfg is not None:
                _set_prop(vmgr, vis_cfg, "config")
                vmgr.set_actor_label("DetectorVisibilityManager")
            st["created"].append("DetectorVisibilityManager")
        except Exception as e:
            _warn("DetectorVisibilityManager: %s" % e)
            st["status"] = "warn"

        les.save_current_level()
        _set_startup_map(report)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def _load_manifest(manifest_dir):
    path = Path(manifest_dir) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError("manifest.json not found in %s" % manifest_dir)
    with open(path) as f:
        data = json.load(f)
    data.setdefault("sub_detectors", [])
    data.setdefault("lights", [])
    data.setdefault("cameras", [])
    return data


def _default_edm4hep_script():
    cand = Path(__file__).resolve().parent / "edm4hep_to_json.py"
    return str(cand) if cand.exists() else ""


def build(config):
    """Run the full content build. `config` keys: manifest_dir (required),
    rebuild_assets (bool), edm4hep_script (path)."""
    if unreal is None:
        raise RuntimeError("ue5_build_content must run inside the Unreal Editor "
                           "(the 'unreal' module is unavailable).")
    manifest_dir = Path(config["manifest_dir"])
    rebuild = bool(config.get("rebuild_assets", False))
    edm4hep_script = config.get("edm4hep_script") or _default_edm4hep_script()

    manifest = _load_manifest(manifest_dir)
    _log("manifest: %d sub-detectors, %d lights, %d cameras"
         % (len(manifest["sub_detectors"]), len(manifest["lights"]),
            len(manifest["cameras"])))

    report = BuildReport()
    stage_import_gltf(report, manifest_dir, manifest, rebuild)
    stage_nanite(report, manifest)
    stage_materials(report, manifest)
    stage_input(report)
    event_cfg, vis_cfg = stage_data_assets(report, manifest, edm4hep_script)
    stage_blueprints(report, event_cfg)
    stage_level(report, manifest, event_cfg, vis_cfg)
    try:
        unreal.EditorAssetLibrary.save_directory("/Game", only_if_is_dirty=True)
    except Exception:
        pass
    return report.finish()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build ColliderVis UE content from a "
                                                 "blend_to_ue5.py manifest.")
    parser.add_argument("--manifest-dir", required=True,
                        help="Directory containing manifest.json + *.gltf")
    parser.add_argument("--edm4hep-script", default=None,
                        help="Absolute path to edm4hep_to_json.py (for DA_EventDisplayConfig)")
    parser.add_argument("--rebuild-assets", action="store_true",
                        help="Force re-import of meshes that already exist")
    # Tolerate UE's '--' arg separator and editor-injected args.
    args, _unknown = parser.parse_known_args(argv)
    return build({
        "manifest_dir": args.manifest_dir,
        "edm4hep_script": args.edm4hep_script,
        "rebuild_assets": args.rebuild_assets,
    })


if __name__ == "__main__":
    main()
