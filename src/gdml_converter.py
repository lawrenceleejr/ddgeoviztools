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
    count: even worst-case 2×3×5×8 = 240 leaf actors fit easily in memory.
    """
    n = lv_name.lower()
    if any(k in n for k in _LEAF_KEYS):
        return 2
    if any(k in n for k in _SUBMOD_KEYS):
        return 3
    if any(k in n for k in _MOD_KEYS):
        return 5
    if any(k in n for k in _TRACKER_KEYS):
        return 8
    if any(k in n for k in _CALO_KEYS):
        return 5
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


def _limit_gdml_placements(
    gdml_path: "Path",
    default_max: int = 20,
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

    for lv_el in structure.findall(tag("volume")):
        # Collect all <physvol> children
        physvols = lv_el.findall(tag("physvol"))
        if not physvols:
            continue

        # Group by referenced logical volume name
        from collections import defaultdict
        groups: dict[str, list] = defaultdict(list)
        for pv in physvols:
            ref_el = pv.find(tag("volumeref"))
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
        if len(remaining) > default_max:
            for pv in remaining[default_max:]:
                lv_el.remove(pv)
                total_removed += 1

    # --- Pass 2: global physvol budget ---
    # Count every physvol still in the structure after pass 1.  If we're over
    # budget, uniformly thin each LV's physvol list until we're within budget.
    all_pvs_by_lv = []
    for lv_el in structure.findall(tag("volume")):
        pvs = lv_el.findall(tag("physvol"))
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
        return sum(
            len(lv.findall(f"{ns_pfx}physvol"))
            for lv in structure.findall(f"{ns_pfx}volume")
        )
    except Exception:
        return 0


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
) -> "list[Path]":
    """
    Split *gdml_path* into per-sub-detector GDMLs using gdml_splitter, then
    convert each piece independently so that peak VTK memory is bounded by
    _GLOBAL_PHYSVOL_BUDGET × tessellation cost rather than the whole scene.

    If a sub-detector chunk still exceeds thresholds after the first split,
    it is recursively re-split at a deeper level in the GDML hierarchy (up to
    _MAX_RESPLIT_DEPTH levels deep).  This handles deeply nested sub-detectors
    (e.g. tracker staves inside layers inside barrels) that remain too large
    after the initial depth=1 split.

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
            # Fall back to converting this chunk directly
            _convert_chunk(gdml_to_split, label_prefix)
            return

        if not split_files:
            shutil.rmtree(split_dir, ignore_errors=True)
            _convert_chunk(gdml_to_split, label_prefix)
            return

        for i, (lv_name, sub_gdml) in enumerate(split_files):
            sub_label = f"{label_prefix}/{lv_name}"
            pruned_sub = _limit_gdml_placements(sub_gdml)

            # Check if this chunk still needs further splitting
            sub_size = Path(pruned_sub).stat().st_size
            sub_pvs = _count_physvols_in_gdml(pruned_sub)

            still_too_large = (
                sub_pvs > _AUTO_SPLIT_PHYSVOL_THRESHOLD
                or sub_size > _AUTO_SPLIT_FILESIZE_BYTES
            )

            if still_too_large and split_depth < _MAX_RESPLIT_DEPTH:
                print(f"  [{_ts()}] [SPLIT d={split_depth}] Chunk {lv_name!r} still large "
                      f"({sub_pvs} pvs, {sub_size/1e6:.1f} MB) — re-splitting at d={split_depth+1}",
                      flush=True)
                _split_and_convert_recursive(pruned_sub, split_depth + 1, sub_label)
            else:
                _convert_chunk(pruned_sub, sub_label)

        shutil.rmtree(split_dir, ignore_errors=True)

    def _convert_chunk(chunk_gdml, label):
        """Convert a single GDML chunk to mesh format."""
        safe_name = label.split("/")[-1][:30].replace("/", "_").replace(" ", "_")
        idx = chunk_counter[0]
        chunk_counter[0] += 1
        chunk_path = output_dir / f"{stem}_det{idx:03d}_{safe_name}.{fmt}"
        print(f"  [{_ts()}] [CONVERT] {label} → {chunk_path.name}", flush=True)
        try:
            partial = _convert_single(chunk_gdml, chunk_path, fmt, t_total)
            results.extend(partial)
        except Exception as exc:
            print(f"  [{_ts()}] [CONVERT] {label} failed: {exc}", flush=True)
        # Aggressively release VTK/pyg4ometry objects from the previous chunk.
        # VTK render windows and mappers hold large C++ allocations that Python
        # gc alone won't reclaim.  Delete the viewer/registry references and
        # collect twice to break weak references and ref cycles.
        gc.collect()
        gc.collect()

    _split_and_convert_recursive(gdml_path, split_depth=1, label_prefix=Path(gdml_path).stem)

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
    input_path: str | Path,
    output_path: str | Path,
    fmt: str = "gltf",
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
    input_path  : path to the input GDML file
    output_path : path for the primary output file; when auto-splitting, sibling
                  files named <stem>_det<NNN>_<lv_name>.<fmt> are written
    fmt         : one of 'gltf', 'glb', 'obj', 'vtp'
                  (inferred from output_path suffix when not supplied)

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

    # ---- Pre-process GDML: limit repeated physical-volume placements ----
    # This prunes hundreds of identical tracker modules / calorimeter layers
    # before pyg4ometry ever touches them, which is far cheaper than letting
    # VTK materialise all of them and then discarding them.
    t0 = time.monotonic()
    gdml_to_load = _limit_gdml_placements(input_path)
    if gdml_to_load != input_path:
        print(f"  [{_ts()}] Placement-pruned GDML ready ({_elapsed(t0)})", flush=True)

    # ---- Complexity check: auto-split if still too many physvols ----
    file_size = Path(gdml_to_load).stat().st_size
    remaining_pvs = _count_physvols_in_gdml(gdml_to_load)
    print(f"  [{_ts()}] {remaining_pvs} physvols after pruning "
          f"(threshold={_AUTO_SPLIT_PHYSVOL_THRESHOLD}), "
          f"file size {file_size/1e6:.1f} MB "
          f"(threshold={_AUTO_SPLIT_FILESIZE_BYTES/1e6:.0f} MB)", flush=True)

    needs_split = (remaining_pvs > _AUTO_SPLIT_PHYSVOL_THRESHOLD
                   or file_size > _AUTO_SPLIT_FILESIZE_BYTES)
    if needs_split:
        reason = []
        if remaining_pvs > _AUTO_SPLIT_PHYSVOL_THRESHOLD:
            reason.append(f"{remaining_pvs} physvols > {_AUTO_SPLIT_PHYSVOL_THRESHOLD}")
        if file_size > _AUTO_SPLIT_FILESIZE_BYTES:
            reason.append(f"file size {file_size/1e6:.1f} MB > "
                         f"{_AUTO_SPLIT_FILESIZE_BYTES/1e6:.0f} MB")
        print(f"  [{_ts()}] Scene is complex ({'; '.join(reason)}) — splitting "
              f"into per-sub-detector chunks to keep peak memory bounded ...",
              flush=True)
        return _auto_split_and_convert(gdml_to_load, output_path, fmt, t_total)

    # ---- Single-pass conversion ----
    return _convert_single(gdml_to_load, output_path, fmt, t_total)
