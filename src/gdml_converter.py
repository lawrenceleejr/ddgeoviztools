"""
GDML to OBJ / GLTF / VTP converter using pyg4ometry + VTK.

Runs fully headless: the VTK render window is put into offscreen mode
before any rendering occurs.  No display or X server required.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Force Mesa software OpenGL before any VTK / OpenGL import.
# These env-vars are read by the Mesa/libGL loader at shared-library init time
# so they must be set before the first import of vtk or pyg4ometry.
# ---------------------------------------------------------------------------
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

import tempfile

import vtk
import pyg4ometry as pg4


SUPPORTED_FORMATS = ("gltf", "glb", "obj", "vtp")


# ---------------------------------------------------------------------------
# GDML pre-processing — limit repeated physical-volume placements
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-LV name-based placement caps
# ---------------------------------------------------------------------------
# Tiers are ordered most-to-least restrictive.  The first matching tier wins.
# Calorimeter absorber/scint layers are the outermost repeated unit — a few
# samples convey the structure.  Tracker leaf elements (sensitive volumes,
# strips, pixels) multiply enormously through the nesting hierarchy: even 10
# placements at each of 3 nesting levels gives 1000 actors; keeping 2–3 at
# each level caps total actors at ~27 while still showing the pattern.

# Tier 0 — true leaf/sensitive elements: keep 2 (just enough to show they exist)
_LEAF_KEYS = (
    "sensitive", "sensor", "hit", "active", "readout",
    "strip", "pixel_chip", "implant", "epitax",
)
# Tier 1 — sub-module level structures
_SUBMOD_KEYS = (
    "stave", "ladder", "plank", "petal", "petal_support",
    "half_stave", "halfstave",
)
# Tier 2 — module / layer repeated at the next level up
_MOD_KEYS = (
    "module", "chip", "sensor_module", "pixel_module",
)
# Tier 3 — overall tracker/TPC structure
_TRACKER_KEYS = (
    "tracker", "trk", "tpc", "silicon", "strip_layer",
    "disk", "ring", "endcap", "barrel_layer",
)
# Tier 4 — calorimeter layers (keep a handful for the visual rhythm)
_CALO_KEYS = (
    "ecal", "hcal", "calo", "calorimeter", "absorber",
    "scint", "crystal", "pbwo", "preshower", "emcal",
)


def _max_placements_for_lv(lv_name: str) -> int:
    """
    Return the placement cap for a child LV referenced by name.

    The tiers ensure that deeply nested tracker hierarchies (sensitive inside
    module inside stave inside layer) stay within a manageable total actor
    count: worst-case 1×2×2×3 = 12 leaf actors for trackers.
    """
    n = lv_name.lower()
    if any(k in n for k in _LEAF_KEYS):
        return 1
    if any(k in n for k in _SUBMOD_KEYS):
        return 2
    if any(k in n for k in _MOD_KEYS):
        return 2
    if any(k in n for k in _TRACKER_KEYS):
        return 3
    if any(k in n for k in _CALO_KEYS):
        return 3
    return 10_000   # effectively unlimited


# Hard ceiling on the total number of physvol elements left in the pruned
# GDML across the entire <structure> section.  Even with per-LV caps,
# a geometry with many different LV names can still produce thousands of
# physvols.  This cap guarantees memory safety regardless of nesting depth.
# Empirically: ~100 physvols → 1–2 GB peak VTK memory from tessellation
# of boolean solids.  Keep at 30 so peak stays under ~500 MB per chunk.
_GLOBAL_PHYSVOL_BUDGET = 30

# If the pruned GDML still has more than this many physvols, automatically
# split it into per-sub-detector GDMLs and convert each independently.
# This bounds peak memory per conversion to roughly _GLOBAL_PHYSVOL_BUDGET × 10 MB.
_AUTO_SPLIT_PHYSVOL_THRESHOLD = 25

# GDML files larger than this (in bytes) are always processed via the
# auto-split path regardless of physvol count, because the XML tree itself
# can consume several GB of RAM for very large files.
_AUTO_SPLIT_FILESIZE_BYTES = 50 * 1024 * 1024   # 50 MB

# Maximum recursion depth for re-splitting sub-detector GDMLs that still
# exceed thresholds after the initial split.  Each level splits at one
# level deeper in the GDML structure hierarchy.
_MAX_RESPLIT_DEPTH = 3

# Tracker sub-detectors have deeply nested repetitive structure (staves,
# modules, layers) that require more aggressive splitting.  Allow up to
# this many recursion levels for names containing tracker-related keywords.
_MAX_RESPLIT_DEPTH_TRACKER = 6

_TRACKER_RESPLIT_KEYS = (
    "tracker", "trk", "tpc", "silicon", "vertex", "inner_tracker",
    "outer_tracker", "barrel_tracker", "endcap_tracker",
    "strip_layer", "disk", "ring", "endcap", "barrel_layer",
)


def _simplify_gdml_envelopes(
    gdml_path: "Path",
) -> "Path":
    """
    Physics-aware GDML simplification for detector visualization.

    Produces the "essence" of the detector: the overall shapes of each
    sub-system without repetitive internal structure.

    Rules by sub-detector type:

    **Calorimeters** (ECal, HCal, Yoke):
      Keep the first and last slice of each layer to show sampling
      structure.  Layer envelopes (Air) become assemblies so they
      don't render.  Stave/inner containers are traversed, not rendered.

    **Trackers** (Vertex, InnerTrackers, OuterTrackers):
      Keep ALL module placements (full cylindrical pattern visible).
      Internal components (silicon, kapton, etc.) are stripped from
      each module.  Air/Vacuum containers become assemblies.

    **Other** (Beampipe, Nozzle, Solenoid):
      Keep the outermost solid, strip internals.

    Returns path to a new temporary GDML with internal structure removed.
    """
    try:
        from lxml import etree
    except ImportError:
        print("  [SIMPLIFY] lxml not available — skipping", flush=True)
        return gdml_path

    tree = etree.parse(str(gdml_path))
    root = tree.getroot()

    ns_map = root.nsmap
    ns_uri = ns_map.get(None, "")
    ns_pfx = f"{{{ns_uri}}}" if ns_uri else ""

    def tag(local):
        return f"{ns_pfx}{local}"

    structure = root.find(tag("structure"))
    if structure is None:
        return gdml_path

    vol_index: dict[str, "etree._Element"] = {}
    for el in structure:
        name = el.get("name")
        if name is not None:
            vol_index[name] = el

    setup = root.find(tag("setup"))
    if setup is None:
        setup = root.find("setup")
    if setup is None:
        return gdml_path
    world_el = setup.find(tag("world"))
    if world_el is None:
        world_el = setup.find("world")
    if world_el is None:
        return gdml_path
    world_name = world_el.get("ref")

    def _get_pvs(vol_el):
        pvs = vol_el.findall(tag("physvol"))
        if not pvs:
            pvs = vol_el.findall("physvol")
        return pvs

    def _is_assembly(vol_el):
        return vol_el.tag in ("assembly", tag("assembly"))

    def _has_solid(vol_el):
        return (vol_el.find(tag("solidref")) is not None
                or vol_el.find("solidref") is not None)

    def _volref(pv_el):
        ref_el = pv_el.find(tag("volumeref"))
        if ref_el is None:
            ref_el = pv_el.find("volumeref")
        return ref_el.get("ref") if ref_el is not None else None

    def _material(vol_el):
        matref = vol_el.find(tag("materialref"))
        if matref is None:
            matref = vol_el.find("materialref")
        return matref.get("ref") if matref is not None else None

    _AIR_MATERIALS = {"Air", "Vacuum", "G4_AIR", "G4_Galactic"}

    total_removed = 0
    # Track which volume NAMES have already been processed to avoid
    # double-modifying shared volume definitions (e.g. 12 staves all
    # referencing the same stave_outer volume).
    _visited: set[str] = set()
    # Volumes whose solid must be kept even though they use Air/Vacuum
    # (e.g. tracker module envelopes that ARE the visible geometry).
    _keep_solid: set[str] = set()

    def _remove_pvs(vol_el):
        nonlocal total_removed
        for pv in list(_get_pvs(vol_el)):
            vol_el.remove(pv)
            total_removed += 1

    def _thin_assembly(vol_el):
        nonlocal total_removed
        pvs = _get_pvs(vol_el)
        seen: set[str] = set()
        for pv in pvs:
            cn = _volref(pv)
            if cn is None:
                continue
            if cn in seen:
                vol_el.remove(pv)
                total_removed += 1
            else:
                seen.add(cn)

    # ------------------------------------------------------------------
    # Calorimeter: envelope → stave(s) → stave_inner → layers → slices
    # Keep first + last slice per layer; layer envelope → assembly.
    # ------------------------------------------------------------------
    def _simplify_calo(vol_name):
        nonlocal total_removed
        if vol_name in _visited:
            return
        _visited.add(vol_name)

        vol_el = vol_index.get(vol_name)
        if vol_el is None:
            return

        if _is_assembly(vol_el):
            _thin_assembly(vol_el)
            for pv in _get_pvs(vol_el):
                cn = _volref(pv)
                if cn:
                    _simplify_calo(cn)
            return

        if not _has_solid(vol_el):
            return

        pvs = _get_pvs(vol_el)
        if not pvs:
            return  # leaf — keep

        # Is this a "layer"? — children are all simple leaves (slices)
        children_are_slices = True
        for pv in pvs:
            cn = _volref(pv)
            if cn is None:
                continue
            cv = vol_index.get(cn)
            if cv is None:
                continue
            if _is_assembly(cv) or _get_pvs(cv):
                children_are_slices = False
                break

        if children_are_slices:
            # Layer — keep only first and last slice so the sampling
            # structure is visible, and convert the layer itself to an
            # <assembly> so its Air bounding-box won't render.
            pvs_list = list(pvs)
            if len(pvs_list) > 2:
                for pv in pvs_list[1:-1]:
                    vol_el.remove(pv)
                    total_removed += 1
            # Strip the layer's own solid/material so only slices render
            for child_tag in ("solidref", "materialref"):
                el = vol_el.find(tag(child_tag))
                if el is None:
                    el = vol_el.find(child_tag)
                if el is not None:
                    vol_el.remove(el)
            vol_el.tag = "assembly"
        else:
            # Container (stave_outer, stave_inner, endcap) — recurse.
            # If it's an Air volume, convert to assembly so its bounding
            # box doesn't render.
            mat = _material(vol_el)
            if mat in _AIR_MATERIALS:
                for child_tag in ("solidref", "materialref"):
                    el = vol_el.find(tag(child_tag))
                    if el is None:
                        el = vol_el.find(child_tag)
                    if el is not None:
                        vol_el.remove(el)
                vol_el.tag = "assembly"
            for pv in list(_get_pvs(vol_el)):
                cn = _volref(pv)
                if cn:
                    _simplify_calo(cn)

    # ------------------------------------------------------------------
    # Tracker: assembly → layers → modules → components
    # Keep ALL modules, strip internal components from each.
    # ------------------------------------------------------------------
    def _simplify_tracker(vol_name):
        if vol_name in _visited:
            return
        _visited.add(vol_name)

        vol_el = vol_index.get(vol_name)
        if vol_el is None:
            return

        if _is_assembly(vol_el):
            # Keep ALL placements so every tracker module position is
            # visible in the final visualisation (full cylindrical pattern).
            for pv in list(_get_pvs(vol_el)):
                cn = _volref(pv)
                if cn:
                    _simplify_tracker(cn)
            return

        if not _has_solid(vol_el):
            return

        pvs = _get_pvs(vol_el)
        mat = _material(vol_el)

        if mat in _AIR_MATERIALS:
            # Check if all children are leaves (no grandchildren) FIRST,
            # before deciding whether to convert to assembly.
            all_leaves = True
            for pv in pvs:
                cn = _volref(pv)
                if cn is None:
                    continue
                cv = vol_index.get(cn)
                if cv is not None and (_is_assembly(cv) or _get_pvs(cv)):
                    all_leaves = False
                    break

            if all_leaves:
                # Module-level Air container (e.g. tracker module box).
                # Keep the solid envelope so it renders as a visible shape
                # in the visualisation — this IS the detector geometry we
                # want.  Only strip the internal components (silicon,
                # kapton, etc.) which are too fine for overview rendering.
                _remove_pvs(vol_el)
                # Mark this volume so the final Air→assembly pass skips it.
                _keep_solid.add(vol_name)
                return

            # Non-leaf Air/Vacuum container (e.g. tracker layer/disk) —
            # convert to <assembly> so pyg4ometry won't tessellate the
            # large envelope solid (avoids big cylinder/tube meshes).
            solidref = vol_el.find(tag("solidref"))
            if solidref is None:
                solidref = vol_el.find("solidref")
            if solidref is not None:
                vol_el.remove(solidref)
            matref = vol_el.find(tag("materialref"))
            if matref is None:
                matref = vol_el.find("materialref")
            if matref is not None:
                vol_el.remove(matref)
            vol_el.tag = "assembly"

            for pv in list(pvs):
                cn = _volref(pv)
                if cn:
                    _simplify_tracker(cn)
            return

        # Non-Air volume with children → module. Strip children.
        if pvs:
            _remove_pvs(vol_el)

    # ------------------------------------------------------------------
    # Generic: keep outermost solid, strip internals
    # ------------------------------------------------------------------
    def _simplify_generic(vol_name):
        if vol_name in _visited:
            return
        _visited.add(vol_name)

        vol_el = vol_index.get(vol_name)
        if vol_el is None:
            return

        if _is_assembly(vol_el):
            # Do NOT thin generic assemblies: the same logical volume is often
            # intentionally placed at multiple positions (e.g. beam-pipe
            # sections at different z, solenoid coils at different φ).
            # _thin_assembly would keep only the first placement and discard
            # the rest, leaving only a single piece near the origin.
            for pv in _get_pvs(vol_el):
                cn = _volref(pv)
                if cn:
                    _simplify_generic(cn)
            return

        if _has_solid(vol_el):
            _remove_pvs(vol_el)

    # ------------------------------------------------------------------
    # Classify each world daughter and apply the right strategy
    # ------------------------------------------------------------------
    _CALO_NAMES = (
        "ecal", "hcal", "yoke", "calo", "calorimeter", "muon",
    )
    _TRACKER_NAMES = (
        "tracker", "vertex", "innertrackers", "outertrackers",
    )

    world_vol = vol_index.get(world_name)
    if world_vol is None:
        return gdml_path

    for pv in _get_pvs(world_vol):
        child_name = _volref(pv)
        if child_name is None:
            continue

        name_lower = child_name.lower()

        if any(k in name_lower for k in _CALO_NAMES):
            print(f"  [SIMPLIFY] {child_name}: calorimeter "
                  f"(first+last slice per layer)", flush=True)
            _simplify_calo(child_name)
        elif any(k in name_lower for k in _TRACKER_NAMES):
            print(f"  [SIMPLIFY] {child_name}: tracker "
                  f"(all modules, strip components)", flush=True)
            _simplify_tracker(child_name)
        else:
            print(f"  [SIMPLIFY] {child_name}: generic "
                  f"(keep envelope)", flush=True)
            _simplify_generic(child_name)

    # ------------------------------------------------------------------
    # Final pass: convert ALL remaining Air/Vacuum volumes to assemblies
    # so no invisible bounding-box envelopes produce meshes.
    # ------------------------------------------------------------------
    air_converted = 0
    for vol_el in list(structure):
        if _is_assembly(vol_el):
            continue
        if not _has_solid(vol_el):
            continue
        # Never convert the world volume or tracker module envelopes
        # to assemblies — pyg4ometry needs the world as a <volume>,
        # and module envelopes ARE the visible detector geometry.
        vname = vol_el.get("name")
        if vname == world_name or vname in _keep_solid:
            continue
        mat = _material(vol_el)
        if mat in _AIR_MATERIALS:
            for child_tag in ("solidref", "materialref"):
                el = vol_el.find(tag(child_tag))
                if el is None:
                    el = vol_el.find(child_tag)
                if el is not None:
                    vol_el.remove(el)
            vol_el.tag = "assembly"
            air_converted += 1
    if air_converted:
        print(f"  [SIMPLIFY] Converted {air_converted} Air/Vacuum "
              f"volumes to assemblies", flush=True)

    if total_removed == 0 and air_converted == 0:
        return gdml_path

    print(f"  [SIMPLIFY] Done: removed {total_removed} physvols, "
          f"converted {air_converted} Air envelopes", flush=True)

    tmp = tempfile.NamedTemporaryFile(
        suffix=".gdml", delete=False, prefix="ddgeo_simplified_"
    )
    tree.write(tmp.name, pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    tmp.close()
    return type(gdml_path)(tmp.name)


def _limit_gdml_placements(
    gdml_path: "Path",
    default_max: int = 10,
) -> "Path":
    """
    Parse *gdml_path* with lxml and remove excess repeated physical-volume
    placements from each logical volume in the <structure> section.

    Two-pass strategy:
      Pass 1 — per-LV-type cap (from _max_placements_for_lv).
      Pass 2 — global budget cap: if total physvols still exceed
               _GLOBAL_PHYSVOL_BUDGET, uniformly thin every LV that has
               more than one placement until the budget is met.

    Returns the path to a temporary GDML file if any placements were removed,
    otherwise returns the original path unchanged.
    """
    try:
        from lxml import etree
    except ImportError:
        print("  [GDML-LIMIT] lxml not available — skipping placement pruning",
              flush=True)
        return gdml_path

    tree = etree.parse(str(gdml_path))
    root = tree.getroot()

    # Handle optional XML namespace
    ns_map   = root.nsmap
    ns_uri   = ns_map.get(None, "")
    ns_pfx   = f"{{{ns_uri}}}" if ns_uri else ""

    def tag(local):
        return f"{ns_pfx}{local}"

    structure = root.find(tag("structure"))
    if structure is None:
        return gdml_path

    total_removed = 0

    # Process both <volume> and <assembly> elements — after simplification
    # many containers are converted to assemblies but still hold physvols.
    all_vol_els = list(structure.findall(tag("volume"))) + \
                  list(structure.findall(tag("assembly")))
    from collections import defaultdict

    for lv_el in all_vol_els:
        # Collect all <physvol> children
        physvols = lv_el.findall(tag("physvol"))
        if not physvols:
            physvols = lv_el.findall("physvol")
        if not physvols:
            continue

        # Group by referenced logical volume name
        groups: dict[str, list] = defaultdict(list)
        for pv in physvols:
            ref_el = pv.find(tag("volumeref"))
            if ref_el is None:
                ref_el = pv.find("volumeref")
            ref    = ref_el.get("ref", "") if ref_el is not None else "__unknown__"
            groups[ref].append(pv)

        for ref_lv, pvs in groups.items():
            cap = _max_placements_for_lv(ref_lv)
            if len(pvs) <= cap:
                continue
            for pv in pvs[cap:]:
                lv_el.remove(pv)
                total_removed += 1

        # Per-LV total cap: even if no single child LV hits the per-type cap,
        # a parent LV with many different child LV types can still end up with
        # hundreds of physvols.  Cap any parent LV to default_max total.
        remaining = lv_el.findall(tag("physvol"))
        if not remaining:
            remaining = lv_el.findall("physvol")
        if len(remaining) > default_max:
            for pv in remaining[default_max:]:
                lv_el.remove(pv)
                total_removed += 1

    # --- Pass 2: global physvol budget ---
    # Count every physvol still in the structure after pass 1.  If we're over
    # budget, uniformly thin each LV's physvol list until we're within budget.
    all_pvs_by_lv = []
    for lv_el in all_vol_els:
        pvs = lv_el.findall(tag("physvol"))
        if not pvs:
            pvs = lv_el.findall("physvol")
        if pvs:
            all_pvs_by_lv.append((lv_el, pvs))

    total_pvs = sum(len(p) for _, p in all_pvs_by_lv)
    if total_pvs > _GLOBAL_PHYSVOL_BUDGET:
        ratio = _GLOBAL_PHYSVOL_BUDGET / total_pvs
        print(f"  [GDML-LIMIT] Global budget: {total_pvs} pvs → "
              f"thinning to {_GLOBAL_PHYSVOL_BUDGET} (ratio={ratio:.2f})",
              flush=True)
        for lv_el, pvs in all_pvs_by_lv:
            keep_n = max(1, int(len(pvs) * ratio))
            # Keep first + evenly spaced sample + last
            if len(pvs) > keep_n:
                step      = len(pvs) // keep_n
                keep_set  = set(range(0, len(pvs), step))
                keep_set.add(0)
                keep_set.add(len(pvs) - 1)
                for idx, pv in enumerate(pvs):
                    if idx not in keep_set:
                        lv_el.remove(pv)
                        total_removed += 1

    if total_removed == 0:
        return gdml_path   # nothing changed — reuse original

    tmp = tempfile.NamedTemporaryFile(
        suffix=".gdml", delete=False, prefix="ddgeo_pruned_"
    )
    tree.write(tmp.name, pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    tmp.close()
    print(f"  [GDML-LIMIT] Removed {total_removed} excess placements → {tmp.name}",
          flush=True)
    return type(gdml_path)(tmp.name)   # return same type (Path or str)


# ---------------------------------------------------------------------------
# GDML garbage collection — strip unreferenced elements after pruning
# ---------------------------------------------------------------------------

def _strip_unreferenced_gdml_elements(gdml_path: "Path") -> "Path":
    """
    Walk the GDML structure starting from the world volume and remove any
    solids, logical volumes, materials, and defines that are no longer
    reachable.

    After ``_limit_gdml_placements`` removes physvols, the tree may contain
    thousands of orphaned definitions.  Stripping them dramatically reduces
    the work pyg4ometry must do during parsing and tessellation.

    Returns a new temp file path if anything was removed, else the original.
    """
    try:
        from lxml import etree
    except ImportError:
        return gdml_path

    tree = etree.parse(str(gdml_path))
    root = tree.getroot()

    ns_uri = root.nsmap.get(None, "")
    ns_pfx = f"{{{ns_uri}}}" if ns_uri else ""

    def tag(local):
        return f"{ns_pfx}{local}"

    # Build indexes
    define_sec   = root.find(tag("define"))
    material_sec = root.find(tag("materials"))
    solids_sec   = root.find(tag("solids"))
    structure    = root.find(tag("structure"))

    if structure is None:
        return gdml_path

    # Index elements by name
    def _index(section):
        if section is None:
            return {}
        return {el.get("name"): el for el in section if el.get("name") is not None}

    define_idx   = _index(define_sec)
    material_idx = _index(material_sec)
    solid_idx    = _index(solids_sec)
    logvol_idx   = _index(structure)

    # Find world volume
    setup = root.find(tag("setup"))
    if setup is None:
        setup = root.find("setup")
    if setup is None:
        return gdml_path
    world_el = setup.find(tag("world"))
    if world_el is None:
        world_el = setup.find("world")
    if world_el is None:
        return gdml_path
    world_name = world_el.get("ref")

    # Walk the tree and collect reachable names
    reached_logvols:   set[str] = set()
    reached_solids:    set[str] = set()
    reached_materials: set[str] = set()
    reached_defines:   set[str] = set()

    def _collect_solid(name):
        if name is None or name in reached_solids:
            return
        reached_solids.add(name)
        el = solid_idx.get(name)
        if el is None:
            return
        ltag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if ltag in ("subtraction", "union", "intersection"):
            for sub in ("first", "second"):
                r = el.find(f"{ns_pfx}{sub}" if ns_pfx else sub)
                if r is not None:
                    _collect_solid(r.get("ref"))
            for ref_tag in ("positionref", "rotationref"):
                r = el.find(f"{ns_pfx}{ref_tag}" if ns_pfx else ref_tag)
                if r is not None:
                    reached_defines.add(r.get("ref"))
        elif ltag == "multiUnion":
            for node in el.findall(f"{ns_pfx}multiUnionNode" if ns_pfx else "multiUnionNode"):
                s = node.find(f"{ns_pfx}solid" if ns_pfx else "solid")
                if s is not None:
                    _collect_solid(s.get("ref"))
                for ref_tag in ("positionref", "rotationref"):
                    r = node.find(f"{ns_pfx}{ref_tag}" if ns_pfx else ref_tag)
                    if r is not None:
                        reached_defines.add(r.get("ref"))
        elif ltag in ("reflectedSolid", "scaledSolid"):
            sr = el.find(f"{ns_pfx}solidref" if ns_pfx else "solidref")
            if sr is not None:
                _collect_solid(sr.get("ref"))

    def _collect_material(name):
        if name is None or name in reached_materials:
            return
        if name.startswith("G4_"):
            return
        reached_materials.add(name)
        mat = material_idx.get(name)
        if mat is None:
            return
        for child in mat:
            ref = child.get("ref")
            if ref:
                _collect_material(ref)

    def _collect_pv_defines(pv):
        for ref_tag in ("positionref", "rotationref", "scaleref"):
            r = pv.find(f"{ns_pfx}{ref_tag}" if ns_pfx else ref_tag)
            if r is not None:
                reached_defines.add(r.get("ref"))

    def _collect_logvol(name):
        if name is None or name in reached_logvols:
            return
        reached_logvols.add(name)
        lv = logvol_idx.get(name)
        if lv is None:
            return
        # Solid
        sref = lv.find(f"{ns_pfx}solidref" if ns_pfx else "solidref")
        if sref is not None:
            _collect_solid(sref.get("ref"))
        # Material
        mref = lv.find(f"{ns_pfx}materialref" if ns_pfx else "materialref")
        if mref is not None:
            _collect_material(mref.get("ref"))
        # Daughters
        for pv in lv.findall(f"{ns_pfx}physvol" if ns_pfx else "physvol"):
            vref = pv.find(f"{ns_pfx}volumeref" if ns_pfx else "volumeref")
            if vref is not None:
                _collect_logvol(vref.get("ref"))
            _collect_pv_defines(pv)

    _collect_logvol(world_name)

    # Remove unreachable elements
    n_removed = 0

    if structure is not None:
        for el in list(structure):
            name = el.get("name")
            if name is not None and name not in reached_logvols:
                structure.remove(el)
                n_removed += 1

    if solids_sec is not None:
        for el in list(solids_sec):
            name = el.get("name")
            if name is not None and name not in reached_solids:
                solids_sec.remove(el)
                n_removed += 1

    if material_sec is not None:
        for el in list(material_sec):
            name = el.get("name")
            if name is not None and name not in reached_materials:
                material_sec.remove(el)
                n_removed += 1

    # Strip orphaned <position> and <rotation> elements from <define>.
    # These are referenced only by physvols and boolean solid transforms,
    # all of which are tracked in reached_defines.  We keep constants,
    # variables, quantities, and matrices — they may be referenced by
    # solid dimension attributes via GDML expressions and are hard to
    # trace reliably.
    _STRIPPABLE_DEFINE_TAGS = {"position", "rotation", "scale"}
    if define_sec is not None:
        for el in list(define_sec):
            name = el.get("name")
            if name is None:
                continue
            local_tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local_tag in _STRIPPABLE_DEFINE_TAGS and name not in reached_defines:
                define_sec.remove(el)
                n_removed += 1

    if n_removed == 0:
        return gdml_path

    tmp = tempfile.NamedTemporaryFile(
        suffix=".gdml", delete=False, prefix="ddgeo_stripped_"
    )
    tree.write(tmp.name, pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    tmp.close()
    print(f"  [GDML-STRIP] Removed {n_removed} unreferenced elements → {tmp.name}",
          flush=True)
    return type(gdml_path)(tmp.name)


# ---------------------------------------------------------------------------
# VTK post-render mesh decimation
# ---------------------------------------------------------------------------

def _decimate_vtk_actors(ren, target_faces_per_actor: int = 20_000):
    """
    Apply vtkQuadricDecimation to every polydata actor in *ren* that has
    more than *target_faces_per_actor* cells.

    This runs AFTER pyg4ometry/VTK has built and rendered the full scene,
    immediately before the GLTF/OBJ/VTP exporter writes to disk.  It does
    not change the scene geometry used during rendering (shadows, lighting)
    — only the polydata stored in each mapper, which is what the exporter
    serialises.

    Reducing per-actor face counts from tens-of-thousands down to ~20 K
    can cut GLTF file sizes (and subsequent loading times) by 10–100×
    for tracker-heavy geometries.
    """
    actors = ren.GetActors()
    actors.InitTraversal()
    n_decimated = 0
    n_actors    = 0

    actor = actors.GetNextActor()
    while actor is not None:
        mapper = actor.GetMapper()
        if mapper is not None:
            try:
                poly = mapper.GetInput()
            except Exception:
                poly = None
            if poly is not None:
                n_cells = poly.GetNumberOfCells()
                n_actors += 1
                if n_cells > target_faces_per_actor:
                    ratio = target_faces_per_actor / n_cells
                    dec   = vtk.vtkQuadricDecimation()
                    dec.SetInputData(poly)
                    dec.SetTargetReduction(1.0 - ratio)
                    dec.Update()
                    out = dec.GetOutput()
                    if out.GetNumberOfCells() > 0:
                        mapper.SetInputData(out)
                        n_decimated += 1

        actor = actors.GetNextActor()

    print(f"  [VTK-DECIM] Decimated {n_decimated}/{n_actors} actors "
          f"(target ≤{target_faces_per_actor:,} faces each)", flush=True)


def _merge_vtk_actors(ren):
    """
    Merge all polydata actors in the renderer into a single actor.

    This produces a single combined mesh in the exported GLTF/OBJ/VTP
    instead of one mesh per logical volume.  The merged actor inherits
    the first actor's visual properties.
    """
    actors = ren.GetActors()
    actors.InitTraversal()

    append = vtk.vtkAppendPolyData()
    n_merged = 0
    first_actor = None
    actor_list = []

    actor = actors.GetNextActor()
    while actor is not None:
        actor_list.append(actor)
        mapper = actor.GetMapper()
        if mapper is not None:
            try:
                poly = mapper.GetInput()
            except Exception:
                poly = None
            if poly is not None and poly.GetNumberOfCells() > 0:
                # Transform polydata by the actor's matrix so positions
                # are in world space before merging.
                mat = actor.GetMatrix()
                if mat is not None:
                    tf = vtk.vtkTransform()
                    tf.SetMatrix(mat)
                    tpd = vtk.vtkTransformPolyDataFilter()
                    tpd.SetInputData(poly)
                    tpd.SetTransform(tf)
                    tpd.Update()
                    append.AddInputData(tpd.GetOutput())
                else:
                    append.AddInputData(poly)
                n_merged += 1
                if first_actor is None:
                    first_actor = actor
        actor = actors.GetNextActor()

    if n_merged <= 1 or first_actor is None:
        print(f"  [VTK-MERGE] {n_merged} actor(s) — no merge needed", flush=True)
        return

    append.Update()
    merged = append.GetOutput()

    # Clean duplicate points from the merge
    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(merged)
    clean.Update()
    merged = clean.GetOutput()

    # Remove all existing actors
    for a in actor_list:
        ren.RemoveActor(a)

    # Add a single merged actor
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(merged)
    merged_actor = vtk.vtkActor()
    merged_actor.SetMapper(mapper)
    # Reset transform since geometry is already in world space
    merged_actor.SetPosition(0, 0, 0)
    merged_actor.SetOrientation(0, 0, 0)
    merged_actor.SetScale(1, 1, 1)
    ren.AddActor(merged_actor)

    print(f"  [VTK-MERGE] Merged {n_merged} actors → 1 "
          f"({merged.GetNumberOfCells():,} faces)", flush=True)


def _count_physvols_in_gdml(gdml_path: "Path") -> int:
    """
    Count the total number of <physvol> elements in a GDML file's <structure>
    section.  Uses lxml for speed; returns 0 if lxml is unavailable.
    """
    try:
        from lxml import etree
    except ImportError:
        return 0
    try:
        tree = etree.parse(str(gdml_path))
        root = tree.getroot()
        ns_uri = root.nsmap.get(None, "")
        ns_pfx = f"{{{ns_uri}}}" if ns_uri else ""
        structure = root.find(f"{ns_pfx}structure")
        if structure is None:
            return 0
        # Count physvols in BOTH <volume> and <assembly> elements.
        # After simplification many containers become assemblies but still
        # hold the bulk of the physvol placements.
        count = 0
        for tag in ("volume", "assembly"):
            for lv in structure.findall(f"{ns_pfx}{tag}"):
                count += len(lv.findall(f"{ns_pfx}physvol"))
        return count
    except Exception:
        return 0


def _split_gdml_physvols(gdml_path: "Path", n_parts: int = 2) -> "list[Path]":
    """
    Split a GDML by distributing physvol placements across *n_parts* files.

    Every part contains all LV/solid/material/define definitions so each is
    a self-contained GDML.  Only the physvol instances inside the assembly /
    volume with the most placements are divided — the first N/2 go to part 0,
    the last N/2 to part 1 (and so on for more parts).  For cylindrical tracker
    layers whose modules are placed in phi order this corresponds roughly to
    the two azimuthal halves.

    Returns a list of temporary GDML paths.  Returns ``[gdml_path]`` unchanged
    if there is nothing meaningful to split (fewer physvols than *n_parts*, or
    *n_parts* ≤ 1).
    """
    try:
        from lxml import etree
    except ImportError:
        return [gdml_path]

    try:
        tree = etree.parse(str(gdml_path))
    except Exception:
        return [gdml_path]

    root   = tree.getroot()
    ns_uri = root.nsmap.get(None, "")
    ns_pfx = f"{{{ns_uri}}}" if ns_uri else ""

    def _tag(local: str) -> str:
        return f"{ns_pfx}{local}"

    structure = root.find(_tag("structure"))
    if structure is None:
        return [gdml_path]

    # Find the volume / assembly that holds the most physvol children
    all_vols = (list(structure.findall(_tag("volume")))
                + list(structure.findall(_tag("assembly"))))
    if not all_vols:
        return [gdml_path]

    target_vol = max(all_vols, key=lambda v: len(v.findall(_tag("physvol"))))
    pvs = target_vol.findall(_tag("physvol"))
    total = len(pvs)

    if total < n_parts:
        return [gdml_path]

    # Build n_parts contiguous index slices
    part_size  = total // n_parts
    boundaries = [(i * part_size, (i + 1) * part_size) for i in range(n_parts - 1)]
    boundaries.append(((n_parts - 1) * part_size, total))

    part_paths: list[Path] = []
    for i, (lo, hi) in enumerate(boundaries):
        # Reparse for each part so each tree is independent
        part_tree = etree.parse(str(gdml_path))
        part_root = part_tree.getroot()
        part_structure = part_root.find(_tag("structure"))
        if part_structure is None:
            continue

        # Find the same target volume in the fresh tree (match by physvol count)
        part_vols = (list(part_structure.findall(_tag("volume")))
                     + list(part_structure.findall(_tag("assembly"))))
        part_target = None
        for vol in part_vols:
            if len(vol.findall(_tag("physvol"))) == total:
                part_target = vol
                break
        if part_target is None:
            continue

        # Remove every physvol outside [lo, hi)
        all_part_pvs = part_target.findall(_tag("physvol"))
        for j, pv in enumerate(all_part_pvs):
            if j < lo or j >= hi:
                part_target.remove(pv)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".gdml", delete=False, prefix=f"ddgeo_pvpart{i}_")
        part_tree.write(tmp.name, pretty_print=True,
                        xml_declaration=True, encoding="UTF-8")
        tmp.close()
        part_paths.append(Path(tmp.name))

    return part_paths if len(part_paths) > 1 else [gdml_path]


def _resolve_to_outer_primitive(solid_name: str, solids_map: dict) -> str:
    """
    Walk a boolean solid chain and return the name of its outermost
    non-boolean primitive operand.

    E.g. subtraction(subtraction(A, B), C) → name of A (a tubs / box / etc.).
    For a non-boolean solid the input name is returned unchanged.
    """
    BOOLEAN_TAGS = {"subtraction", "union", "intersection", "multiUnion"}
    visited: set[str] = set()
    name = solid_name
    while name not in visited:
        visited.add(name)
        el = solids_map.get(name)
        if el is None:
            break
        ltag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if ltag not in BOOLEAN_TAGS:
            break  # reached a primitive (tubs, box, polycone, …)
        # Follow the "first" operand (the outer shape in a subtraction)
        ns_pfx = "{" + el.tag.split("}")[0].lstrip("{") + "}" if "}" in el.tag else ""
        first = el.find(f"{ns_pfx}first") if ns_pfx else el.find("first")
        if first is None:
            break
        name = first.get("ref", name)
    return name


def _replace_booleans_with_outer_primitive(gdml_path: "Path") -> "Path":
    """
    Replace every boolean solid referenced by a <volume> with the outermost
    non-boolean primitive in its operand chain.

    This is the last-resort fallback when even a single-physvol chunk still
    causes OCC tessellation to hang.  The outermost primitive (typically a
    ``<tubs>`` for tracker modules) tessellates in milliseconds.

    Returns the original path unchanged if nothing needs replacing.
    """
    try:
        from lxml import etree
    except ImportError:
        return gdml_path

    tree = etree.parse(str(gdml_path))
    root = tree.getroot()
    ns_uri = root.nsmap.get(None, "")
    ns_pfx = f"{{{ns_uri}}}" if ns_uri else ""

    def _tag(local: str) -> str:
        return f"{ns_pfx}{local}"

    solids_sec = root.find(_tag("solids"))
    structure  = root.find(_tag("structure"))
    if solids_sec is None or structure is None:
        return gdml_path

    solids_map = {el.get("name"): el
                  for el in solids_sec if el.get("name") is not None}

    changed = 0
    for vol in list(structure.findall(_tag("volume"))):
        sref = vol.find(_tag("solidref"))
        if sref is None:
            continue
        orig  = sref.get("ref", "")
        outer = _resolve_to_outer_primitive(orig, solids_map)
        if outer != orig:
            sref.set("ref", outer)
            changed += 1

    if changed == 0:
        return gdml_path

    print(f"  [FALLBACK] Replaced {changed} boolean solid(s) with outermost "
          f"primitive (last-resort OCC fallback)", flush=True)
    tmp = tempfile.NamedTemporaryFile(
        suffix=".gdml", delete=False, prefix="ddgeo_fallback_")
    tree.write(tmp.name, pretty_print=True,
               xml_declaration=True, encoding="UTF-8")
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Per-chunk subprocess conversion with timeout
# ---------------------------------------------------------------------------

def _chunk_convert_worker(
    q: "multiprocessing.Queue",
    chunk_gdml_str: str,
    chunk_path_str: str,
    fmt: str,
    t_total: float,
) -> None:
    """
    Subprocess worker: call ``_convert_single`` and place the result on *q*.

    Must be a module-level function (not a nested closure) so that
    ``multiprocessing`` can pickle it when using the 'spawn' start method.
    """
    try:
        results = _convert_single(
            Path(chunk_gdml_str), Path(chunk_path_str), fmt, t_total)
        q.put((True, [str(p) for p in results], None))
    except Exception as exc:
        q.put((False, [], str(exc)))


def _run_chunk_with_timeout(
    chunk_gdml: "Path",
    chunk_path: "Path",
    fmt: str,
    t_total: float,
    timeout_secs: int,
) -> "tuple[bool, list[Path], str | None]":
    """
    Run ``_convert_single`` in a child process; kill it if it exceeds
    *timeout_secs*.

    Returns ``(success, result_paths, error_or_None)``.
    """
    import multiprocessing as _mp

    # Daemon processes cannot spawn children (raises "daemonic processes are
    # not allowed to have children").  When we are already inside a daemon
    # worker (e.g. a --parallel pool worker), fall back to a direct call in
    # the current process — the outer pool timeout will still kill us if we
    # exceed the per-detector limit.
    if _mp.current_process().daemon:
        try:
            partial = _convert_single(chunk_gdml, chunk_path, fmt, t_total)
            return True, partial, None
        except Exception as exc:
            return False, [], str(exc)

    ctx  = _mp.get_context("spawn")
    q    = ctx.Queue()
    proc = ctx.Process(
        target=_chunk_convert_worker,
        args=(q, str(chunk_gdml), str(chunk_path), fmt, t_total),
    )
    proc.start()
    proc.join(timeout_secs)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
        return False, [], f"timed out after {timeout_secs}s"

    if not q.empty():
        ok, paths, err = q.get_nowait()
        return ok, [Path(p) for p in paths], err

    return False, [], "child process exited without result"


def _merge_gltf_files(
    gltf_paths: "list[Path]",
    output_path: "Path",
    name: str,
) -> None:
    """
    Merge multiple GLTF files into a single GLTF.

    VTK's ``vtkGLTFExporter`` (with ``InlineDataOn()``) produces one inline
    base64 buffer **per bufferView** — not one buffer for the whole file.
    Each ``bufferView[N]`` references ``buffer[N]``.  This function handles
    that layout by decoding *every* buffer, concatenating their data into
    a single merged buffer, and remapping all ``bufferView.buffer`` indices
    to 0 with adjusted ``byteOffset`` values.

    The merged file contains all nodes from all input files under a single
    scene.  Only the root nodes of each file's scene are promoted to scene
    roots; child nodes are reached through their parent's ``children`` array.
    Camera nodes are skipped (they carry no geometry).

    This is a lightweight JSON + base64 operation — no VTK or pyg4ometry
    needed — so it adds negligible overhead after the expensive conversion.
    """
    import base64
    import json
    import shutil

    if not gltf_paths:
        return
    if len(gltf_paths) == 1:
        if gltf_paths[0].resolve() != output_path.resolve():
            shutil.copy2(gltf_paths[0], output_path)
        _rename_gltf_nodes(output_path, name)
        return

    merged_buf = bytearray()
    all_nodes: list[dict] = []
    all_meshes: list[dict] = []
    all_accessors: list[dict] = []
    all_buffer_views: list[dict] = []
    all_materials: list[dict] = []
    scene_root_indices: list[int] = []
    asset: dict = {"version": "2.0", "generator": "ddgeoviztools"}

    for gltf_path in gltf_paths:
        try:
            data = json.loads(gltf_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        # ---- Decode ALL buffers from this file ----
        # VTK produces one buffer per bufferView, each with its own inline
        # base64 data URI.  We decode every buffer and record where each
        # one lands in the merged buffer.
        file_buffers = data.get("buffers", [])
        # Map: old buffer index → byte offset in merged_buf
        buf_start: dict[int, int] = {}
        for buf_idx, buf in enumerate(file_buffers):
            uri = buf.get("uri", "")
            if uri.startswith("data:") and "," in uri:
                raw = base64.b64decode(uri.split(",", 1)[1])
            else:
                raw = b""

            # Pad to 4-byte alignment
            pad = (4 - len(merged_buf) % 4) % 4
            if pad and len(merged_buf) > 0:
                merged_buf.extend(b"\x00" * pad)

            buf_start[buf_idx] = len(merged_buf)
            merged_buf.extend(raw)

        # ---- Index offsets for remapping ----
        bv_off   = len(all_buffer_views)
        acc_off  = len(all_accessors)
        mesh_off = len(all_meshes)
        mat_off  = len(all_materials)
        node_off = len(all_nodes)

        # ---- bufferViews: remap buffer index & byte offset ----
        for bv in data.get("bufferViews", []):
            new_bv = dict(bv)
            old_buf = bv.get("buffer", 0)
            base = buf_start.get(old_buf, 0)
            new_bv["buffer"] = 0
            new_bv["byteOffset"] = bv.get("byteOffset", 0) + base
            all_buffer_views.append(new_bv)

        # ---- accessors: remap bufferView index ----
        for acc in data.get("accessors", []):
            new_acc = dict(acc)
            if "bufferView" in acc:
                new_acc["bufferView"] = acc["bufferView"] + bv_off
            all_accessors.append(new_acc)

        # ---- materials: collect as-is ----
        for mat in data.get("materials", []):
            all_materials.append(mat)

        # ---- meshes: remap accessor & material indices ----
        for mesh in data.get("meshes", []):
            new_mesh: dict = {"name": name, "primitives": []}
            for prim in mesh.get("primitives", []):
                new_prim: dict = {}
                if "attributes" in prim:
                    new_prim["attributes"] = {
                        k: v + acc_off for k, v in prim["attributes"].items()
                    }
                if "indices" in prim:
                    new_prim["indices"] = prim["indices"] + acc_off
                if "mode" in prim:
                    new_prim["mode"] = prim["mode"]
                if "material" in prim:
                    new_prim["material"] = prim["material"] + mat_off
                new_mesh["primitives"].append(new_prim)
            all_meshes.append(new_mesh)

        # ---- nodes: remap mesh, children; skip camera nodes ----
        # Build a set of nodes that carry cameras (no geometry to merge).
        camera_nodes: set[int] = set()
        for ni, node in enumerate(data.get("nodes", [])):
            if "camera" in node:
                camera_nodes.add(ni)

        # Remap table: old node index → new node index (None if skipped)
        node_remap: dict[int, int | None] = {}
        for ni, node in enumerate(data.get("nodes", [])):
            if ni in camera_nodes:
                node_remap[ni] = None
                continue
            new_node: dict = {"name": name}
            if "mesh" in node:
                new_node["mesh"] = node["mesh"] + mesh_off
            if "children" in node:
                # Remap later after all node indices are known
                new_node["_old_children"] = node["children"]
            for key in ("translation", "rotation", "scale", "matrix"):
                if key in node:
                    new_node[key] = node[key]
            node_remap[ni] = len(all_nodes)
            all_nodes.append(new_node)

        # Fixup children references now that we have the remap table
        for new_ni, new_node in enumerate(all_nodes[node_off:], start=node_off):
            if "_old_children" in new_node:
                new_children = []
                for old_ci in new_node.pop("_old_children"):
                    mapped = node_remap.get(old_ci)
                    if mapped is not None:
                        new_children.append(mapped)
                if new_children:
                    new_node["children"] = new_children

        # Collect root nodes for the merged scene
        file_roots = set()
        for scene in data.get("scenes", []):
            for ri in scene.get("nodes", []):
                file_roots.add(ri)
        if not file_roots:
            file_roots = set(range(len(data.get("nodes", []))))
        for ri in sorted(file_roots):
            mapped = node_remap.get(ri)
            if mapped is not None:
                scene_root_indices.append(mapped)

    if not all_nodes:
        return

    # ---- Build merged GLTF ----
    merged_uri = (
        "data:application/octet-stream;base64,"
        + base64.b64encode(bytes(merged_buf)).decode("ascii")
    )
    merged_gltf: dict = {
        "asset": asset,
        "scene": 0,
        "scenes": [{"nodes": scene_root_indices}],
        "nodes": all_nodes,
        "meshes": all_meshes,
        "accessors": all_accessors,
        "bufferViews": all_buffer_views,
        "buffers": [{"uri": merged_uri, "byteLength": len(merged_buf)}],
    }
    if all_materials:
        merged_gltf["materials"] = all_materials

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(merged_gltf, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"  [MERGE] Wrote {output_path.name}: "
          f"{len(all_nodes)} nodes, {len(all_meshes)} meshes, "
          f"{len(merged_buf)/1e6:.2f} MB buffer", flush=True)


def _rename_gltf_nodes(output_path: "Path", name: str) -> None:
    """
    Patch a GLTF JSON file so that all nodes and meshes are named *name*.

    When imported into Blender this produces a single object called *name*
    instead of VTK's auto-generated names like "actor0" / "mesh0".
    """
    import json

    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception:
        return

    changed = False
    for node in data.get("nodes", []):
        node["name"] = name
        changed = True
    for mesh in data.get("meshes", []):
        mesh["name"] = name
        changed = True

    if changed:
        output_path.write_text(
            json.dumps(data, separators=(",", ":")),
            encoding="utf-8",
        )


def _write_vtk_export(
    ren: "vtk.vtkRenderer",
    renWin: "vtk.vtkRenderWindow",
    output_path: "Path",
    fmt: str,
) -> None:
    """Write the current VTK scene to *output_path* in the requested format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt in ("gltf", "glb"):
        exp = vtk.vtkGLTFExporter()
        exp.SetFileName(str(output_path))
        exp.SetActiveRenderer(ren)
        exp.SetRenderWindow(renWin)
        exp.InlineDataOn()
        exp.Write()
        # Rename nodes/meshes to match the sub-detector name
        _rename_gltf_nodes(output_path, output_path.stem)
    elif fmt == "obj":
        prefix = str(output_path.with_suffix(""))
        exp = vtk.vtkOBJExporter()
        exp.SetFilePrefix(prefix)
        exp.SetRenderWindow(renWin)
        exp.Write()
    elif fmt == "vtp":
        exp = vtk.vtkSingleVTPExporter()
        exp.SetFileName(str(output_path))
        exp.SetRenderWindow(renWin)
        exp.Write()


def _find_renwin(viewer) -> "vtk.vtkRenderWindow":
    """Locate the vtkRenderWindow inside a VtkViewer instance."""
    for attr in ("renWin", "renderWindow", "window", "_renWin"):
        candidate = getattr(viewer, attr, None)
        if isinstance(candidate, vtk.vtkRenderWindow):
            return candidate
    for val in vars(viewer).values():
        if isinstance(val, vtk.vtkRenderWindow):
            return val
    raise RuntimeError("Could not locate a vtkRenderWindow on the VtkViewer object.")


def _ts() -> str:
    """Current wall-clock timestamp string, e.g. '18:23:01'."""
    return time.strftime("%H:%M:%S")


def _elapsed(t0: float) -> str:
    """Human-readable elapsed seconds since t0."""
    s = time.monotonic() - t0
    if s < 60:
        return f"{s:.1f}s"
    m, s = divmod(s, 60)
    return f"{int(m)}m{s:.0f}s"


def _auto_split_and_convert(
    gdml_path: "Path",
    output_path: "Path",
    fmt: str,
    t_total: float,
    simplify: bool = True,
    chunk_timeout: "int | None" = None,
    skip_existing: bool = False,
) -> "list[Path]":
    """
    Split *gdml_path* into per-sub-detector GDMLs using gdml_splitter, then
    convert each piece independently so that peak VTK memory is bounded.

    If a sub-detector chunk still exceeds thresholds after the first split,
    it is recursively re-split at a deeper level in the GDML hierarchy (up to
    _MAX_RESPLIT_DEPTH levels deep).

    When *simplify* is True, per-chunk placement limits are skipped because
    the simplification already made physics-aware pruning choices (e.g. keeping
    all tracker module placements).

    *chunk_timeout* — if set, each individual chunk conversion runs in a child
    process and is killed after this many seconds.  On timeout the chunk is
    split in half by physvol placement index and each half is retried
    independently (recursively, until single-physvol GDMLs are reached).
    This avoids indefinite hangs caused by OCC tessellation of complex solids.

    *skip_existing* — if True, skip any chunk whose output file already exists
    and is non-empty (useful for resuming an interrupted run).

    Each output file is named  <output_path.stem>_det<NNN>_<lv_name>.<fmt>.
    Returns the list of successfully written output paths.
    """
    import gc
    import shutil
    import tempfile

    # Import the GDML splitter (pure lxml, no VTK/pyg4ometry needed here)
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from gdml_splitter import split_gdml
    except ImportError as exc:
        print(f"  [{_ts()}] [AUTO-SPLIT] Cannot import gdml_splitter: {exc} "
              f"— falling back to single-pass (high memory)", flush=True)
        return _convert_single(gdml_path, output_path, fmt, t_total)

    output_dir = output_path.parent
    stem       = output_path.stem
    results: list[Path] = []
    chunk_counter = [0]   # mutable counter for unique filenames across recursion

    # In simplify mode each physvol is already a simple solid (no children),
    # so VTK can handle more actors per chunk than in the full-detail case.
    pvs_threshold = 50_000 if simplify else _AUTO_SPLIT_PHYSVOL_THRESHOLD

    # Maximum sub-detectors from a single split before we stop splitting.
    # If split produces more than this, the children are individual physvol
    # placements (e.g. 15K modules in one layer) — converting them as
    # separate GDMLs would be wasteful; better to convert the parent directly.
    _MAX_SPLIT_CHILDREN = 100

    def _split_and_convert_recursive(gdml_to_split, split_depth, label_prefix):
        """Recursively split and convert a GDML file."""
        split_dir = Path(tempfile.mkdtemp(prefix=f"ddgeo_split_d{split_depth}_"))
        try:
            print(f"  [{_ts()}] [SPLIT d={split_depth}] Splitting {label_prefix} → "
                  f"{split_dir.name}/", flush=True)
            split_files = split_gdml(gdml_to_split, split_dir, depth=1)
        except Exception as exc:
            print(f"  [{_ts()}] [SPLIT d={split_depth}] Split failed: {exc}",
                  flush=True)
            shutil.rmtree(split_dir, ignore_errors=True)
            _convert_chunk(gdml_to_split, label_prefix)
            return

        if not split_files:
            shutil.rmtree(split_dir, ignore_errors=True)
            _convert_chunk(gdml_to_split, label_prefix)
            return

        # If depth=1 produced only 1 result, the GDML has a wrapper world
        # volume with a single daughter.  Try depth=2 to reach that
        # daughter's children (the actual sub-systems we want to split on).
        if len(split_files) == 1:
            shutil.rmtree(split_dir, ignore_errors=True)
            split_dir = Path(tempfile.mkdtemp(prefix=f"ddgeo_split_d{split_depth}b_"))
            try:
                split_files = split_gdml(gdml_to_split, split_dir, depth=2)
            except Exception as exc:
                print(f"  [{_ts()}] [SPLIT d={split_depth}] depth=2 split failed: {exc}",
                      flush=True)
                shutil.rmtree(split_dir, ignore_errors=True)
                _convert_chunk(gdml_to_split, label_prefix)
                return
            if len(split_files) <= 1:
                # Can't split further — convert directly
                shutil.rmtree(split_dir, ignore_errors=True)
                _convert_chunk(gdml_to_split, label_prefix)
                return

        # Guard: too many children means we've reached individual physvol
        # placements (e.g. thousands of identical module placements in a
        # tracker layer).  Converting each as a separate GDML is wasteful;
        # convert the parent assembly directly instead.
        if len(split_files) > _MAX_SPLIT_CHILDREN:
            print(f"  [{_ts()}] [SPLIT d={split_depth}] {len(split_files)} children "
                  f"(> {_MAX_SPLIT_CHILDREN}) — converting directly", flush=True)
            shutil.rmtree(split_dir, ignore_errors=True)
            _convert_chunk(gdml_to_split, label_prefix)
            return

        for i, (lv_name, sub_gdml) in enumerate(split_files):
            sub_label = f"{label_prefix}/{lv_name}"

            # Do NOT run _limit_gdml_placements on auto-split chunks.
            # The recursive splitting already keeps each chunk within a
            # manageable physvol count.  Running placement limits on top
            # strips the actual detector physvols (silicon sensors, modules)
            # while leaving invisible Air/Vacuum containers, producing
            # GLTF files with only world-volume bounding boxes.
            # Only strip unreferenced elements (cheap, no geometry loss).
            pruned_sub = _strip_unreferenced_gdml_elements(sub_gdml)

            # Check if this chunk still needs further splitting
            sub_size = Path(pruned_sub).stat().st_size
            sub_pvs = _count_physvols_in_gdml(pruned_sub)

            still_too_large = (
                sub_pvs > pvs_threshold
                or sub_size > _AUTO_SPLIT_FILESIZE_BYTES
            )

            # Tracker sub-detectors get a higher recursion depth limit
            _lv_lower = lv_name.lower()
            max_depth = _MAX_RESPLIT_DEPTH_TRACKER \
                if any(k in _lv_lower for k in _TRACKER_RESPLIT_KEYS) \
                else _MAX_RESPLIT_DEPTH

            if still_too_large and split_depth < max_depth:
                print(f"  [{_ts()}] [SPLIT d={split_depth}] Chunk {lv_name!r} still large "
                      f"({sub_pvs} pvs, {sub_size/1e6:.1f} MB) — re-splitting at "
                      f"d={split_depth+1} (max={max_depth})",
                      flush=True)
                _split_and_convert_recursive(pruned_sub, split_depth + 1, sub_label)
            else:
                _convert_chunk(pruned_sub, sub_label)

        shutil.rmtree(split_dir, ignore_errors=True)

    # Maximum physvol-fraction split depth (2^8 = 256 halves — single physvol)
    _MAX_PHYSVOL_SPLIT_DEPTH = 8

    def _convert_chunk(chunk_gdml, label, pv_split_depth=0):
        """
        Convert a single GDML chunk to mesh format.

        When *chunk_timeout* is set:
          1. Attempt conversion in a child subprocess with the timeout.
          2. On failure / timeout: split the chunk in half by physvol index
             and retry each half independently (recursive, up to
             _MAX_PHYSVOL_SPLIT_DEPTH levels).  Successfully converted halves
             are merged back into a single output file.
          3. If a single-physvol chunk still hangs: replace boolean solids with
             their outermost primitive operand (last resort) and retry once.
        """
        safe_name = label.split("/")[-1][:30].replace("/", "_").replace(" ", "_")
        idx = chunk_counter[0]
        chunk_counter[0] += 1
        chunk_path = output_dir / f"{stem}_det{idx:03d}_{safe_name}.{fmt}"

        # --resume: skip chunks whose output already exists and is non-empty
        if skip_existing and chunk_path.exists() and chunk_path.stat().st_size > 0:
            print(f"  [{_ts()}] [SKIP] {chunk_path.name} already exists — "
                  f"skipping (--resume)", flush=True)
            results.append(chunk_path)
            return

        print(f"  [{_ts()}] [CONVERT] {label} → {chunk_path.name}", flush=True)

        if chunk_timeout is None:
            # No timeout: original behaviour — direct call in this process
            try:
                partial = _convert_single(chunk_gdml, chunk_path, fmt, t_total)
                results.extend(partial)
            except Exception as exc:
                print(f"  [{_ts()}] [CONVERT] {label} failed: {exc}", flush=True)
            gc.collect()
            gc.collect()
            return

        # ---- Subprocess with timeout ----
        ok, partial, err = _run_chunk_with_timeout(
            chunk_gdml, chunk_path, fmt, t_total, chunk_timeout)

        if ok:
            results.extend(partial)
            gc.collect()
            gc.collect()
            return

        # First attempt failed or timed out
        print(f"  [{_ts()}] [WARN] {label} failed ({err})", flush=True)

        # ---- Physvol-fraction split ----
        if pv_split_depth < _MAX_PHYSVOL_SPLIT_DEPTH:
            part_gdmls = _split_gdml_physvols(Path(chunk_gdml), n_parts=2)
            if len(part_gdmls) > 1:
                n_pvs = _count_physvols_in_gdml(Path(chunk_gdml))
                print(
                    f"  [{_ts()}] [PV-SPLIT] Splitting {label} ({n_pvs} physvols) "
                    f"into {len(part_gdmls)} halves "
                    f"(pv_split_depth={pv_split_depth + 1})",
                    flush=True,
                )
                part_results: list[Path] = []
                for pi, pg in enumerate(part_gdmls):
                    part_out = (output_dir
                                / f"{stem}_det{idx:03d}_{safe_name}_p{pi}.{fmt}")
                    ok2, pp, err2 = _run_chunk_with_timeout(
                        pg, part_out, fmt, t_total, chunk_timeout)
                    if ok2:
                        part_results.extend(pp)
                    else:
                        # This half also failed — recurse to split it further
                        print(
                            f"  [{_ts()}] [PV-SPLIT] Half {pi} of {label} "
                            f"also failed ({err2}) — splitting deeper",
                            flush=True,
                        )
                        saved_len = len(results)
                        # Recursively convert this half (adds its results
                        # to the outer `results` list as a side effect).
                        _convert_chunk(pg, f"{label}_p{pi}",
                                        pv_split_depth + 1)
                        # Harvest results added by the recursive call so we
                        # can merge them together with the other halves, then
                        # remove them from `results` (they'll be re-added as
                        # part of the merged chunk_path below).
                        new_results = results[saved_len:]
                        part_results.extend(new_results)
                        del results[saved_len:]

                if part_results:
                    if fmt in ("gltf", "glb") and len(part_results) > 1:
                        try:
                            _merge_gltf_files(part_results, chunk_path,
                                              chunk_path.stem)
                            for p in part_results:
                                if (p.resolve() != chunk_path.resolve()
                                        and p.exists()):
                                    p.unlink()
                            results.append(chunk_path)
                        except Exception as merge_exc:
                            print(
                                f"  [{_ts()}] [PV-SPLIT] Merge failed "
                                f"({merge_exc}) — keeping individual parts",
                                flush=True,
                            )
                            results.extend(part_results)
                    else:
                        results.extend(part_results)
                else:
                    print(
                        f"  [{_ts()}] [PV-SPLIT] No parts succeeded for "
                        f"{label} — chunk skipped",
                        flush=True,
                    )

                # Clean up temporary part GDMLs
                for pg in part_gdmls:
                    try:
                        Path(pg).unlink()
                    except Exception:
                        pass

                gc.collect()
                gc.collect()
                return

        # ---- Last resort: outer-primitive fallback ----
        # Reached when physvol splitting cannot help (e.g. single physvol
        # still hangs because the solid definition itself is pathological).
        print(
            f"  [{_ts()}] [FALLBACK] {label}: physvol split exhausted — "
            f"retrying with outer-primitive solid replacement",
            flush=True,
        )
        fallback_gdml = _replace_booleans_with_outer_primitive(Path(chunk_gdml))
        ok3, partial3, err3 = _run_chunk_with_timeout(
            fallback_gdml, chunk_path, fmt, t_total, chunk_timeout)
        if ok3:
            results.extend(partial3)
            print(
                f"  [{_ts()}] [FALLBACK] {label}: outer-primitive fallback "
                f"succeeded",
                flush=True,
            )
        else:
            print(
                f"  [{_ts()}] [ERROR] {label}: outer-primitive fallback also "
                f"failed ({err3}) — skipping chunk",
                flush=True,
            )
        if fallback_gdml != Path(chunk_gdml):
            try:
                fallback_gdml.unlink()
            except Exception:
                pass

        # Aggressively release VTK/pyg4ometry objects from the previous chunk.
        gc.collect()
        gc.collect()

    _split_and_convert_recursive(gdml_path, split_depth=1, label_prefix=Path(gdml_path).stem)

    # ---- Merge split GLTF/GLB chunks back into one file ----
    # The splitting was only needed to keep VTK/pyg4ometry peak memory
    # bounded during conversion.  Now that every chunk has been exported,
    # merge them into a single GLTF so each sub-detector is one logical
    # object in downstream tools (Blender, three.js, etc.).
    if fmt in ("gltf", "glb") and len(results) > 1:
        print(
            f"  [{_ts()}] [MERGE] Merging {len(results)} GLTF chunks back "
            f"into one file → {output_path.name}",
            flush=True,
        )
        t0 = time.monotonic()
        try:
            _merge_gltf_files(results, output_path, output_path.stem)
            # Remove individual chunk files (they've been merged)
            for p in results:
                if p.resolve() != output_path.resolve() and p.exists():
                    p.unlink()
            results = [output_path]
            print(f"  [{_ts()}] [MERGE] Done ({_elapsed(t0)})", flush=True)
        except Exception as exc:
            print(
                f"  [{_ts()}] [MERGE] Failed: {exc} — keeping individual chunks",
                flush=True,
            )

    total_sz = sum(p.stat().st_size for p in results if p.exists()) / 1e6
    print(
        f"  [{_ts()}] [AUTO-SPLIT] Done — {len(results)} file(s), "
        f"{total_sz:.1f} MB total  ({_elapsed(t_total)})",
        flush=True,
    )
    return results


def _convert_single(
    gdml_path: "Path",
    output_path: "Path",
    fmt: str,
    t_total: float,
) -> "list[Path]":
    """
    Inner single-GDML conversion pipeline (build VTK scene, render, export).
    Called by convert_gdml after pruning has already been applied.
    Returns a one-element list containing the output path on success.

    All VTK/pyg4ometry objects are explicitly deleted after export so that
    gc can reclaim the (often very large) C++ allocations before the next
    chunk is processed.
    """
    import gc

    reader = None
    viewer = None
    ren    = None
    renWin = None

    try:
        # ---- Read GDML ----
        t0 = time.monotonic()
        print(f"  [{_ts()}] Reading {Path(gdml_path).name} ...", flush=True)
        reader = pg4.gdml.Reader(str(gdml_path))
        reg    = reader.getRegistry()
        world  = reg.getWorldVolume()
        n_volumes = len(reg.logicalVolumeDict)
        print(f"  [{_ts()}] Read done ({_elapsed(t0)}) — {n_volumes} logical volumes",
              flush=True)

        # ---- Build scene ----
        t0 = time.monotonic()
        print(f"  [{_ts()}] Building geometry scene ...", flush=True)
        viewer = _offscreen_viewer()
        viewer.addLogicalVolume(world)
        print(f"  [{_ts()}] Scene built ({_elapsed(t0)})", flush=True)

        ren    = viewer.ren
        renWin = _find_renwin(viewer)
        renWin.SetOffScreenRendering(1)

        # ---- Pre-render decimation: caps peak VTK render memory ----
        # Complex solids (polycones, tessellated volumes) can produce millions of
        # faces per actor after pyg4ometry tessellation.  Decimating the mapper
        # inputs *before* Render() prevents the renderer from holding all that
        # data in RAM simultaneously.  This is the most effective point to
        # reduce memory for intricate geometries.
        t0 = time.monotonic()
        _decimate_vtk_actors(ren, target_faces_per_actor=10_000)
        print(f"  [{_ts()}] Pre-render decimation done ({_elapsed(t0)})", flush=True)

        t0 = time.monotonic()
        print(f"  [{_ts()}] Rendering ...", flush=True)
        renWin.Render()
        print(f"  [{_ts()}] Render done ({_elapsed(t0)})", flush=True)

        # ---- Post-render decimation (safety net for geometry added by render) ----
        t0 = time.monotonic()
        _decimate_vtk_actors(ren, target_faces_per_actor=20_000)
        print(f"  [{_ts()}] Post-render decimation done ({_elapsed(t0)})", flush=True)

        # ---- Merge all actors into a single mesh ----
        t0 = time.monotonic()
        _merge_vtk_actors(ren)
        print(f"  [{_ts()}] Actor merge done ({_elapsed(t0)})", flush=True)

        # ---- Export ----
        t0 = time.monotonic()
        print(f"  [{_ts()}] Exporting {fmt.upper()} → {output_path} ...", flush=True)
        _write_vtk_export(ren, renWin, output_path, fmt)

        sz = output_path.stat().st_size if output_path.exists() else 0
        print(
            f"  [{_ts()}] Export done ({_elapsed(t0)}) — "
            f"{sz/1e6:.1f} MB  total: {_elapsed(t_total)}",
            flush=True,
        )
        return [output_path]

    finally:
        # ---- Explicit cleanup ----
        # VTK render windows, mappers, and pyg4ometry registries hold large
        # C++ allocations.  Explicitly finalize and delete them so gc can
        # reclaim memory before the next chunk is processed.
        if renWin is not None:
            try:
                renWin.Finalize()
            except Exception:
                pass
        del renWin, ren, viewer, reader
        gc.collect()
        gc.collect()


def _offscreen_viewer() -> pg4.visualisation.VtkViewer:
    """
    Create a pyg4ometry VtkViewer and immediately enable offscreen rendering
    so the window never needs to appear on a display.
    """
    viewer = pg4.visualisation.VtkViewer()

    # pyg4ometry stores the render window as one of several possible attrs
    renWin = None
    for attr in ("renWin", "renderWindow", "window", "_renWin"):
        candidate = getattr(viewer, attr, None)
        if isinstance(candidate, vtk.vtkRenderWindow):
            renWin = candidate
            break

    if renWin is None:
        # Last resort: walk all attributes
        for attr in vars(viewer).values():
            if isinstance(attr, vtk.vtkRenderWindow):
                renWin = attr
                break

    if renWin is None:
        raise RuntimeError(
            "Could not locate a vtkRenderWindow on the VtkViewer object. "
            "Check your pyg4ometry version."
        )

    renWin.SetOffScreenRendering(1)
    return viewer


def convert_gdml(
    input_path: "str | Path",
    output_path: "str | Path",
    fmt: str = "gltf",
    simplify: bool = True,
    chunk_timeout: "int | None" = None,
    skip_existing: bool = False,
) -> "list[Path]":
    """
    Convert a GDML file to OBJ, GLTF (or GLB), or VTP.

    For geometrically complex inputs the GDML is first pruned to remove
    repeated identical placements.  If the pruned scene still exceeds
    _AUTO_SPLIT_PHYSVOL_THRESHOLD physvols it is automatically split into one
    GDML per top-level sub-detector and each is converted independently,
    keeping peak VTK memory bounded.

    Parameters
    ----------
    input_path     : path to the input GDML file
    output_path    : path for the primary output file; when auto-splitting,
                     sibling files named <stem>_det<NNN>_<lv_name>.<fmt>
                     are written
    fmt            : one of 'gltf', 'glb', 'obj', 'vtp'
                     (inferred from output_path suffix when not supplied)
    simplify       : if True, strip internal structure and keep only envelope
                     shapes for each sub-detector (fast "essence" mode)
    chunk_timeout  : per-chunk subprocess timeout in seconds.  When set, each
                     auto-split chunk runs in a child process and is killed after
                     this many seconds.  On timeout the chunk is split in half by
                     physvol placement index and each half retried recursively.
    skip_existing  : if True, skip any chunk whose output file already exists
                     and is non-empty (resume an interrupted run).

    Returns
    -------
    List of written output Path objects (one per converted sub-detector, or
    a single-element list for simple scenes).
    """
    input_path  = Path(input_path)
    output_path = Path(output_path)
    fmt = (fmt or output_path.suffix).lower().lstrip(".")

    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{fmt}'. Choose from: {', '.join(SUPPORTED_FORMATS)}"
        )

    t_total = time.monotonic()

    # ---- Simplify mode: strip internal structure, keep envelopes only ----
    gdml_to_process = input_path
    if simplify:
        t0 = time.monotonic()
        print(f"  [{_ts()}] Simplify mode: stripping internal structure ...",
              flush=True)
        gdml_to_process = _simplify_gdml_envelopes(input_path)
        if gdml_to_process != input_path:
            print(f"  [{_ts()}] Simplified GDML ready ({_elapsed(t0)})", flush=True)

    # ---- Complexity check (early) ----
    # Decide BEFORE pruning whether auto-split is needed.  If it is, skip
    # the aggressive global placement limit — auto-split handles memory
    # bounding per-chunk.  Applying _limit_gdml_placements first would
    # destroy most of the geometry (e.g. 5000 tracker modules → 30) that
    # auto-split was designed to distribute across manageable chunks.
    raw_pvs   = _count_physvols_in_gdml(gdml_to_process)
    file_size = Path(gdml_to_process).stat().st_size
    needs_split = (
        raw_pvs > _AUTO_SPLIT_PHYSVOL_THRESHOLD
        or file_size > _AUTO_SPLIT_FILESIZE_BYTES
    )

    if needs_split:
        reason = []
        if raw_pvs > _AUTO_SPLIT_PHYSVOL_THRESHOLD:
            reason.append(f"{raw_pvs} physvols > {_AUTO_SPLIT_PHYSVOL_THRESHOLD}")
        if file_size > _AUTO_SPLIT_FILESIZE_BYTES:
            reason.append(f"file size {file_size/1e6:.1f} MB > "
                         f"{_AUTO_SPLIT_FILESIZE_BYTES/1e6:.0f} MB")
        print(f"  [{_ts()}] Scene is complex ({'; '.join(reason)}) — going "
              f"directly to auto-split (per-chunk limits provide memory safety)",
              flush=True)
        return _auto_split_and_convert(
            gdml_to_process, output_path, fmt, t_total,
            simplify=simplify,
            chunk_timeout=chunk_timeout,
            skip_existing=skip_existing,
        )

    # ---- Pre-process GDML: limit repeated physical-volume placements ----
    # Only for single-pass conversion (small scenes).
    # In simplify mode the physics-aware simplification already prunes the
    # geometry intentionally (e.g. keeping all tracker module placements).
    # Running the generic placement limiter on top would undo that work.
    if simplify:
        gdml_to_load = gdml_to_process
    else:
        t0 = time.monotonic()
        gdml_to_load = _limit_gdml_placements(gdml_to_process)
        if gdml_to_load != gdml_to_process:
            print(f"  [{_ts()}] Placement-pruned GDML ready ({_elapsed(t0)})", flush=True)

    # ---- Strip unreferenced elements (solids, logvols, materials, defines) ----
    # After pruning or simplification many definitions become orphaned.
    # Removing them shrinks the file and avoids unnecessary pyg4ometry work.
    t0 = time.monotonic()
    gdml_stripped = _strip_unreferenced_gdml_elements(gdml_to_load)
    if gdml_stripped != gdml_to_load:
        gdml_to_load = gdml_stripped
    print(f"  [{_ts()}] Unreferenced-element strip done ({_elapsed(t0)})", flush=True)

    # ---- Single-pass conversion ----
    return _convert_single(gdml_to_load, output_path, fmt, t_total)
