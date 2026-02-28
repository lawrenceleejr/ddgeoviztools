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

import vtk
import pyg4ometry as pg4


SUPPORTED_FORMATS = ("gltf", "glb", "obj", "vtp")


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

    # ---- Read GDML ----
    t0 = time.monotonic()
    print(f"  [{_ts()}] Reading {input_path.name} ...", flush=True)
    reader = pg4.gdml.Reader(str(input_path))
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
