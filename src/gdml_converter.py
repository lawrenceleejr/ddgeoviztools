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

# Name fragments that identify highly-repeated sub-detector types.
# These come last in a depth-first traversal, so pyg4ometry materialises
# every placement as a separate VTK actor — the dominant source of slowness.
_TRACKER_KEYS = (
    "tracker", "trk", "tpc", "silicon", "strip", "stave",
    "module", "disk", "petal", "ring", "endcap", "barrel_layer",
    "sensitive",
)
_CALO_KEYS = (
    "ecal", "hcal", "calo", "calorimeter", "absorber",
    "scint", "crystal", "pbwo", "preshower", "emcal",
)


def _max_placements_for_lv(lv_name: str) -> int:
    """
    Return the maximum number of physical-volume daughters to materialise
    for a logical volume whose name contains recognisable keywords.

    Trackers have hundreds-to-thousands of replicated modules; 20 is enough
    to convey the structure.  Calorimeters often have 50-100+ layers; 8 is
    sufficient for visualisation.  Everything else is left uncapped (returns
    a very large number so nothing is removed).
    """
    n = lv_name.lower()
    if any(k in n for k in _CALO_KEYS):
        return 8
    if any(k in n for k in _TRACKER_KEYS):
        return 20
    return 10_000   # effectively unlimited


def _limit_gdml_placements(
    gdml_path: "Path",
    default_max: int = 50,
) -> "Path":
    """
    Parse *gdml_path* with lxml and remove excess repeated physical-volume
    placements from each logical volume in the <structure> section.

    For each logical volume the daughters are grouped by the logical-volume
    they reference (via <volumeref ref="…">).  If a single referenced LV
    appears more than *max* times, the excess placements are deleted.  The
    name-specific cap from _max_placements_for_lv() is applied per child LV.

    Returns the path to a temporary GDML file if any placements were removed,
    otherwise returns the original path unchanged (no temp file written).
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

        # Also apply the default global cap across ALL daughters of this LV
        remaining = lv_el.findall(tag("physvol"))
        if len(remaining) > default_max * len(groups):
            cap_all = default_max * max(1, len(groups))
            for pv in remaining[cap_all:]:
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
) -> Path:
    """
    Convert a GDML file to OBJ, GLTF (or GLB), or VTP.

    Parameters
    ----------
    input_path  : path to the input GDML file
    output_path : path for the output file
    fmt         : one of 'gltf', 'glb', 'obj', 'vtp'
                  (inferred from output_path suffix when not supplied)

    Returns
    -------
    Path of the written output file.
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

    # ---- Read GDML ----
    t0 = time.monotonic()
    print(f"  [{_ts()}] Reading {Path(gdml_to_load).name} ...", flush=True)
    reader = pg4.gdml.Reader(str(gdml_to_load))
    reg    = reader.getRegistry()
    world  = reg.getWorldVolume()
    n_volumes = len(reg.logicalVolumeDict)
    print(f"  [{_ts()}] Read done ({_elapsed(t0)}) — {n_volumes} logical volumes", flush=True)

    # ---- Build scene ----
    t0 = time.monotonic()
    print(f"  [{_ts()}] Building geometry scene ...", flush=True)
    viewer = _offscreen_viewer()
    viewer.addLogicalVolume(world)
    print(f"  [{_ts()}] Scene built ({_elapsed(t0)})", flush=True)

    # Locate renderer and render window from the (now populated) viewer
    ren    = viewer.ren
    renWin = None
    for attr in ("renWin", "renderWindow", "window", "_renWin"):
        candidate = getattr(viewer, attr, None)
        if isinstance(candidate, vtk.vtkRenderWindow):
            renWin = candidate
            break
    if renWin is None:
        for val in vars(viewer).values():
            if isinstance(val, vtk.vtkRenderWindow):
                renWin = val
                break
    if renWin is None:
        raise RuntimeError("VTK render window lost after addLogicalVolume().")

    renWin.SetOffScreenRendering(1)

    t0 = time.monotonic()
    print(f"  [{_ts()}] Rendering ...", flush=True)
    renWin.Render()
    print(f"  [{_ts()}] Render done ({_elapsed(t0)})", flush=True)

    # ---- Decimate VTK actors before export ----
    # Reduces per-actor face counts to ≤20 K triangles via QEM decimation.
    # This shrinks GLTF file sizes dramatically for tracker-heavy geometries
    # (thousands of small modules with dense tessellations) while keeping all
    # visible shapes intact for photorealistic rendering.
    t0 = time.monotonic()
    _decimate_vtk_actors(ren, target_faces_per_actor=20_000)
    print(f"  [{_ts()}] Actor decimation done ({_elapsed(t0)})", flush=True)

    # ---- Export ----
    output_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    print(f"  [{_ts()}] Exporting {fmt.upper()} → {output_path} ...", flush=True)

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

    sz = output_path.stat().st_size if output_path.exists() else 0
    print(
        f"  [{_ts()}] Export done ({_elapsed(t0)}) — "
        f"{sz/1e6:.1f} MB  total: {_elapsed(t_total)}",
        flush=True,
    )

    return output_path
