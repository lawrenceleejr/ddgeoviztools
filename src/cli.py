"""
ddgeoviztools — command-line interface

Split and/or convert ddsim/DD4hep GDML detector geometry files.

Subcommands
-----------
  split          Split a GDML into one file per sub-detector system.
  convert        Convert a GDML file to OBJ, GLTF, or VTP.
  split-convert  Split then convert each sub-detector in one step.
  blender-scene  Build a Blender .blend scene from converted mesh files.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Worker for parallel / timed conversion (must be module-level to be picklable)
# ---------------------------------------------------------------------------

def _convert_worker(args_tuple):
    """
    Called in a child process.  Returns (lv_name, output_path, error_str|None).
    """
    # Support 4-tuple (legacy), 5-tuple (with simplify), and 7-tuple
    # (with simplify + chunk_timeout + skip_existing)
    chunk_timeout = None
    skip_existing = False
    if len(args_tuple) == 7:
        lv_name, gdml_path, out_path, fmt, simplify, chunk_timeout, skip_existing = args_tuple
    elif len(args_tuple) == 5:
        lv_name, gdml_path, out_path, fmt, simplify = args_tuple
    else:
        lv_name, gdml_path, out_path, fmt = args_tuple
        simplify = True  # default on for legacy 4-tuple callers
    # Re-import inside child so env vars are set before vtk loads
    from gdml_converter import convert_gdml
    try:
        convert_gdml(input_path=gdml_path, output_path=out_path, fmt=fmt,
                     simplify=simplify, chunk_timeout=chunk_timeout,
                     skip_existing=skip_existing)
        return (lv_name, out_path, None)
    except Exception as exc:
        return (lv_name, out_path, str(exc))


def _run_with_timeout(lv_name, gdml_path, out_path, fmt, timeout):
    """
    Run conversion in a child process; kill it if it exceeds *timeout* seconds.
    Returns (success: bool, error_msg: str|None).
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    def _worker(q):
        r = _convert_worker((lv_name, gdml_path, out_path, fmt))
        q.put(r)

    proc = ctx.Process(target=_worker, args=(result_queue,))
    proc.start()
    proc.join(timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
        return False, f"timed out after {timeout}s"

    if not result_queue.empty():
        _, _, err = result_queue.get_nowait()
        return (err is None), err
    return False, "child process exited without result"


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_split(args: argparse.Namespace) -> int:
    from gdml_splitter import split_gdml

    detectors = (
        [d.strip() for d in args.detectors.split(",") if d.strip()]
        if args.detectors
        else None
    )

    print(f"Splitting {args.gdml_file}", flush=True)
    print(f"  depth={args.depth}  output-dir={args.output_dir}", flush=True)
    if detectors:
        print(f"  filter: {detectors}", flush=True)

    try:
        results = split_gdml(
            input_path=args.gdml_file,
            output_dir=args.output_dir,
            depth=args.depth,
            detectors=detectors,
        )
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr, flush=True)
        return 1

    print(f"\nDone — {len(results)} GDML file(s) written to {args.output_dir}/", flush=True)
    for lv_name, path in results:
        print(f"  {lv_name:50s}  →  {path.name}", flush=True)
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    from gdml_converter import convert_gdml

    output_path = Path(args.output)
    fmt = args.format or output_path.suffix.lstrip(".")
    if not fmt:
        print(
            "Error: cannot infer output format from extension. "
            "Use --format obj|gltf|vtp",
            file=sys.stderr,
        )
        return 1

    simplify       = not getattr(args, "no_simplify", False)
    chunk_timeout  = getattr(args, "chunk_timeout", None)
    skip_existing  = getattr(args, "resume", False)
    print(f"Converting {args.gdml_file}  →  {output_path}  [{fmt.upper()}]", flush=True)
    if simplify:
        print("  Simplify mode: keeping envelope shapes only (no internal structure)", flush=True)
    if chunk_timeout:
        print(f"  chunk-timeout: {chunk_timeout}s per auto-split chunk", flush=True)
    if skip_existing:
        print("  resume: skipping chunks with existing output files", flush=True)
    try:
        written = convert_gdml(
            input_path=args.gdml_file,
            output_path=output_path,
            fmt=fmt,
            simplify=simplify,
            chunk_timeout=chunk_timeout,
            skip_existing=skip_existing,
        )
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr, flush=True)
        return 1

    if len(written) == 1:
        print(f"\nDone — wrote {written[0]}", flush=True)
    else:
        print(f"\nDone — wrote {len(written)} file(s):", flush=True)
        for p in written:
            print(f"  {p}", flush=True)
    return 0


def cmd_split_convert(args: argparse.Namespace) -> int:
    from gdml_splitter import split_gdml

    fmt           = args.format
    output_dir    = Path(args.output_dir)
    gdml_dir      = output_dir / "gdml"
    timeout       = args.timeout      # seconds per detector, or None
    parallel      = args.parallel     # number of workers, or 1 for serial
    simplify      = not getattr(args, "no_simplify", False)
    chunk_timeout = getattr(args, "chunk_timeout", None)
    skip_existing = getattr(args, "resume", False)
    skip_set      = set()
    if args.skip_detectors:
        skip_set = {d.strip() for d in args.skip_detectors.split(",") if d.strip()}

    detectors = (
        [d.strip() for d in args.detectors.split(",") if d.strip()]
        if args.detectors
        else None
    )

    # --- Step 1: split ---
    print(f"[1/2] Splitting {args.gdml_file}", flush=True)
    print(f"      depth={args.depth}  gdml output → {gdml_dir}/", flush=True)
    try:
        gdml_files = split_gdml(
            input_path=args.gdml_file,
            output_dir=gdml_dir,
            depth=args.depth,
            detectors=detectors,
        )
    except Exception as exc:
        print(f"\nSplit error: {exc}", file=sys.stderr, flush=True)
        return 1

    print(f"\n      {len(gdml_files)} sub-detector(s) found.\n", flush=True)

    # Apply skip filter
    if skip_set:
        skipped_names = [lv for lv, _ in gdml_files if lv in skip_set]
        gdml_files = [(lv, p) for lv, p in gdml_files if lv not in skip_set]
        if skipped_names:
            print(f"      Skipping {len(skipped_names)}: {', '.join(skipped_names)}\n", flush=True)

    # --- Step 2: convert each ---
    print(f"[2/2] Converting to {fmt.upper()} → {output_dir}/", flush=True)
    if simplify:
        print(f"      simplify: envelope shapes only (no internal structure)", flush=True)
    if timeout:
        print(f"      timeout: {timeout}s per detector", flush=True)
    if chunk_timeout:
        print(f"      chunk-timeout: {chunk_timeout}s per auto-split chunk", flush=True)
    if skip_existing:
        print(f"      resume: skipping chunks with existing output files", flush=True)
    if parallel > 1:
        print(f"      parallel workers: {parallel}", flush=True)

    work_items = [
        (lv_name, gdml_path, output_dir / f"{gdml_path.stem}.{fmt}", fmt, simplify,
         chunk_timeout, skip_existing)
        for lv_name, gdml_path in gdml_files
    ]

    errors: list[tuple[str, str]] = []
    t_all = time.monotonic()

    if parallel > 1:
        # --- Parallel mode ---
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=parallel) as pool:
            futures = {}
            for item in work_items:
                lv_name = item[0]
                print(f"\n  [{lv_name}] submitting ...", flush=True)
                future = pool.apply_async(_convert_worker, args=(item,))
                futures[lv_name] = (future, item, time.monotonic())

            for lv_name, (future, item, t0) in futures.items():
                print(f"\n  [{lv_name}] waiting for result ...", flush=True)
                try:
                    _, out_path, err = future.get(timeout=timeout)
                    elapsed = time.monotonic() - t0
                    if err:
                        print(f"  [{lv_name}] FAILED ({elapsed:.0f}s): {err}", file=sys.stderr, flush=True)
                        errors.append((lv_name, err))
                    else:
                        print(f"  [{lv_name}] done ({elapsed:.0f}s)", flush=True)
                except multiprocessing.TimeoutError:
                    elapsed = time.monotonic() - t0
                    msg = f"timed out after {elapsed:.0f}s"
                    print(f"  [{lv_name}] SKIPPED — {msg}", file=sys.stderr, flush=True)
                    errors.append((lv_name, msg))
                except Exception as exc:
                    elapsed = time.monotonic() - t0
                    print(f"  [{lv_name}] FAILED ({elapsed:.0f}s): {exc}", file=sys.stderr, flush=True)
                    errors.append((lv_name, str(exc)))
                    if args.fail_fast:
                        print("Aborting (--fail-fast).", file=sys.stderr, flush=True)
                        pool.terminate()
                        return 1

    else:
        # --- Serial mode (original behaviour, with optional timeout) ---
        for lv_name, gdml_path, out_path, _, _simplify, _ct, _se in work_items:
            print(f"\n  [{lv_name}]", flush=True)
            t0 = time.monotonic()

            if timeout:
                ok, err = _run_with_timeout(lv_name, gdml_path, out_path, fmt, timeout)
                elapsed = time.monotonic() - t0
                if not ok:
                    print(f"  [{lv_name}] SKIPPED — {err}", file=sys.stderr, flush=True)
                    errors.append((lv_name, err))
                    if args.fail_fast:
                        print("Aborting (--fail-fast).", file=sys.stderr, flush=True)
                        return 1
                else:
                    print(f"  [{lv_name}] done ({elapsed:.0f}s)", flush=True)
            else:
                from gdml_converter import convert_gdml
                try:
                    convert_gdml(input_path=gdml_path, output_path=out_path,
                                 fmt=fmt, simplify=simplify,
                                 chunk_timeout=chunk_timeout,
                                 skip_existing=skip_existing)
                except Exception as exc:
                    print(f"  [WARN] conversion failed: {exc}", file=sys.stderr, flush=True)
                    errors.append((lv_name, str(exc)))
                    if args.fail_fast:
                        print("Aborting (--fail-fast).", file=sys.stderr, flush=True)
                        return 1

    total_elapsed = time.monotonic() - t_all
    m, s = divmod(total_elapsed, 60)
    elapsed_str = f"{int(m)}m{s:.0f}s" if m else f"{s:.1f}s"

    n_ok = len(work_items) - len(errors)
    print(
        f"\nDone — {n_ok}/{len(work_items)} sub-detector(s) converted "
        f"successfully in {elapsed_str}.  Output in {output_dir}/",
        flush=True,
    )
    if errors:
        print("\nFailed/skipped sub-detectors:", file=sys.stderr, flush=True)
        for name, msg in errors:
            print(f"  {name}: {msg}", file=sys.stderr, flush=True)
        return 1
    return 0


def cmd_blender_scene(args: argparse.Namespace) -> int:
    mesh_dir    = Path(args.mesh_dir)
    output_path = Path(args.output)

    # Resolve phi range
    if args.no_phi_cut:
        phi_min = -180.0
        phi_max =  180.0
    else:
        phi_min = args.phi_min if args.phi_min is not None else 0.0
        phi_max = phi_min + args.phi_cut

    print(f"Building Blender scene from {mesh_dir}/", flush=True)
    print(f"  format={args.format}  output={output_path}", flush=True)
    if not args.no_phi_cut:
        print(f"  phi cutaway: [{phi_min:.1f}°, {phi_max:.1f}°]", flush=True)
    else:
        print(f"  phi cutaway: disabled (full detector)", flush=True)
    if not args.no_bevel:
        print(f"  edge bevel: {args.bevel_width} mm", flush=True)

    # gdml_to_blender.py uses bpy which is only available inside Blender's
    # bundled Python interpreter.  Spawn Blender headlessly and pass it our
    # script; arguments are JSON-encoded after the '--' separator.
    blender_exe = shutil.which("blender")
    if blender_exe is None:
        print(
            "Error: 'blender' not found in PATH. "
            "Make sure Blender is installed in the container.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    script = Path(__file__).parent / "gdml_to_blender.py"
    # Use absolute paths so they resolve correctly inside Blender's working dir
    kwargs = json.dumps({
        "mesh_dir":       str(mesh_dir.resolve()),
        "output_path":    str(output_path.resolve()),
        "fmt":            args.format,
        "phi_min":        phi_min,
        "phi_max":        phi_max,
        "no_phi_cut":     args.no_phi_cut,
        "weld_threshold": args.weld_threshold,
        "bevel_width_mm": args.bevel_width,
        "no_bevel":       args.no_bevel,
        "no_env_sphere":  args.no_env_sphere,
        "volume_density": args.volume_density,
    })

    cmd = [blender_exe, "--background", "--python", str(script), "--", kwargs]
    print(f"  Launching: blender --background --python {script.name} ...", flush=True)
    result = subprocess.run(cmd)

    # Blender exits 0 even when a Python script raises an unhandled exception,
    # so we validate success by confirming the output file was actually written.
    output_abs = output_path.resolve()
    if result.returncode != 0:
        print(f"\nError: Blender exited with code {result.returncode}.", file=sys.stderr, flush=True)
        return result.returncode
    if not output_abs.exists():
        print(
            f"\nError: Blender exited successfully but did not write {output_abs}.\n"
            "Check the Blender output above for Python errors.",
            file=sys.stderr, flush=True,
        )
        return 1

    print(f"\nDone — open {output_path} in Blender.", flush=True)
    print("  Active camera: Cam_Transverse (XY cross-section, Z=beam into screen).", flush=True)
    if not args.no_phi_cut:
        print(f"  Phi cutaway: [{phi_min:.0f}°, {phi_max:.0f}°] baked via bmesh bisect "
              f"(clean intersection edges).", flush=True)
        print("  Boolean modifier (disabled): enable per-object for non-destructive cut.",
              flush=True)
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ddgeoviztools",
        description=(
            "Split and visualize ddsim/DD4hep GDML detector geometries.\n"
            "All paths inside Docker should be under /data (mounted from host)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- split ----
    p_split = sub.add_parser(
        "split",
        help="Split a GDML file into one GDML per sub-detector.",
    )
    p_split.add_argument("gdml_file", help="Input GDML file (e.g. /data/MAIA_260226.gdml)")
    p_split.add_argument(
        "--output-dir", required=True, metavar="DIR",
        help="Directory to write split GDML files into.",
    )
    p_split.add_argument(
        "--depth", type=int, default=1, metavar="N",
        help=(
            "How many levels below the world volume to split at. "
            "1 = direct daughters (default). Use 2 if the world has a single "
            "top-level envelope that itself contains the sub-detectors."
        ),
    )
    p_split.add_argument(
        "--detectors", metavar="D1,D2,...",
        help=(
            "Comma-separated list of logical-volume names to include. "
            "Omit to include all sub-detectors at the specified depth."
        ),
    )
    p_split.set_defaults(func=cmd_split)

    # ---- convert ----
    p_conv = sub.add_parser(
        "convert",
        help="Convert a GDML file to OBJ, GLTF, or VTP.",
    )
    p_conv.add_argument("gdml_file", help="Input GDML file")
    p_conv.add_argument(
        "--output", required=True, metavar="FILE",
        help="Output file path. Extension sets the format if --format is omitted.",
    )
    p_conv.add_argument(
        "--format", choices=["obj", "gltf", "glb", "vtp"], default=None,
        help="Output format. Inferred from --output extension when omitted.",
    )
    p_conv.add_argument(
        "--simplify", action="store_true", default=True,
        help=(
            "Physics-aware simplification (ON by default): calorimeters keep "
            "per-layer shapes (strip slices), trackers keep module envelopes "
            "(strip components), Air/Vacuum containers produce no mesh."
        ),
    )
    p_conv.add_argument(
        "--no-simplify", action="store_true",
        help="Disable physics-aware simplification (full detail, slower).",
    )
    p_conv.add_argument(
        "--chunk-timeout", type=int, default=1200, metavar="SECS",
        dest="chunk_timeout",
        help=(
            "Per auto-split chunk timeout in seconds.  If a single chunk "
            "takes longer than SECS, it is split in half by physvol placement "
            "index and each half retried independently.  Recommended: 1800. "
            "Default: 1200 (20 min)."
        ),
    )
    p_conv.add_argument(
        "--resume", action="store_true",
        help=(
            "Skip chunks whose output file already exists (resume interrupted run)."
        ),
    )
    p_conv.set_defaults(func=cmd_convert)

    # ---- split-convert ----
    p_sc = sub.add_parser(
        "split-convert",
        help="Split a GDML and convert each sub-detector in one step.",
    )
    p_sc.add_argument("gdml_file", help="Input GDML file")
    p_sc.add_argument(
        "--output-dir", required=True, metavar="DIR",
        help=(
            "Output directory. GDML splits go to <DIR>/gdml/, "
            "mesh files go to <DIR>/<name>.<fmt>."
        ),
    )
    p_sc.add_argument(
        "--format", choices=["obj", "gltf", "glb", "vtp"], default="gltf",
        help="Output mesh format (default: gltf).",
    )
    p_sc.add_argument(
        "--depth", type=int, default=1, metavar="N",
        help="Levels below world volume to split at (default: 1).",
    )
    p_sc.add_argument(
        "--detectors", metavar="D1,D2,...",
        help="Comma-separated LV names to include (default: all).",
    )
    p_sc.add_argument(
        "--skip-detectors", metavar="D1,D2,...",
        help=(
            "Comma-separated LV names to skip entirely "
            "(e.g. '--skip-detectors InnerTrackers' to skip a known-slow detector)."
        ),
    )
    p_sc.add_argument(
        "--timeout", type=int, default=None, metavar="SECS",
        help=(
            "Kill and skip any detector conversion that takes longer than SECS seconds. "
            "Useful for skipping runaway geometries like InnerTrackers. "
            "Default: no timeout (wait indefinitely)."
        ),
    )
    p_sc.add_argument(
        "--parallel", type=int, default=1, metavar="N",
        help=(
            "Number of detectors to convert in parallel (default: 1 = serial). "
            "Each worker runs in its own process. "
            "Set to the number of available CPU cores for maximum throughput, "
            "but note that complex geometries use significant memory per worker."
        ),
    )
    p_sc.add_argument(
        "--fail-fast", action="store_true",
        help="Abort on the first conversion failure (default: warn and continue).",
    )
    p_sc.add_argument(
        "--simplify", action="store_true", default=True,
        help=(
            "Physics-aware simplification (ON by default): calorimeters keep "
            "per-layer shapes (strip slices), trackers keep module envelopes "
            "(strip components), Air/Vacuum containers produce no mesh."
        ),
    )
    p_sc.add_argument(
        "--no-simplify", action="store_true",
        help="Disable physics-aware simplification (full detail, slower).",
    )
    p_sc.add_argument(
        "--chunk-timeout", type=int, default=1200, metavar="SECS",
        dest="chunk_timeout",
        help=(
            "Per auto-split chunk timeout in seconds.  If a single chunk "
            "(e.g. one tracker layer) takes longer than SECS, it is split "
            "in half by physvol placement index and each half is retried "
            "independently in a subprocess.  Halves are split recursively "
            "until they succeed.  Last resort: replace complex boolean solids "
            "with their outermost primitive.  Recommended: 1800 (30 min). "
            "Default: 1200 (20 min)."
        ),
    )
    p_sc.add_argument(
        "--resume", action="store_true",
        help=(
            "Skip auto-split chunks whose output file already exists and is "
            "non-empty.  Use this to restart an interrupted run without "
            "re-processing already-completed chunks."
        ),
    )
    p_sc.set_defaults(func=cmd_split_convert)

    # ---- blender-scene ----
    p_bl = sub.add_parser(
        "blender-scene",
        help="Build a Blender .blend scene from converted mesh files.",
    )
    p_bl.add_argument(
        "mesh_dir",
        help=(
            "Directory containing mesh files produced by 'convert' or "
            "'split-convert' (e.g. /data/output/)."
        ),
    )
    p_bl.add_argument(
        "--output", required=True, metavar="FILE",
        help="Output .blend file path (e.g. /data/MAIA_260226.blend).",
    )
    p_bl.add_argument(
        "--format", choices=["gltf", "glb", "obj", "vtp"], default="gltf",
        help="Mesh format to look for in MESH_DIR (default: gltf).",
    )
    p_bl.add_argument(
        "--phi-cut", type=float, default=90.0, metavar="DEGREES",
        help=(
            "Angular width of the visible phi sector in degrees (default: 90 = π/2). "
            "phi=atan2(Y,X); Z=beam. "
            "90 = first quadrant [0°,90°]. 180 = upper half. 360 = full detector. "
            "Ignored if --no-phi-cut is set."
        ),
    )
    p_bl.add_argument(
        "--phi-min", type=float, default=None, metavar="DEGREES",
        help=(
            "Override phi range lower bound (degrees). "
            "Default: 0 (i.e. sector starts at +X)."
        ),
    )
    p_bl.add_argument(
        "--no-phi-cut", action="store_true",
        help="Disable the phi-cutaway modifier entirely (show full detector).",
    )
    p_bl.add_argument(
        "--weld-threshold", type=float, default=1e-4, metavar="MM",
        help=(
            "Distance threshold for the Weld modifier that merges duplicate "
            "vertices (mm, default: 1e-4). Set to 0 to disable."
        ),
    )
    p_bl.add_argument(
        "--bevel-width", type=float, default=0.2, metavar="MM",
        dest="bevel_width",
        help=(
            "Width of the microscopic edge chamfer added to all sub-detectors "
            "(mm, default: 0.2). Produces specular highlights on sharp edges. "
            "Set to 0 or use --no-bevel to disable."
        ),
    )
    p_bl.add_argument(
        "--no-bevel", action="store_true",
        help="Disable the Bevel modifier (no edge chamfering).",
    )
    p_bl.add_argument(
        "--no-env-sphere", action="store_true",
        help=(
            "Disable the matte environment sphere that surrounds the detector "
            "and acts as a soft-light dome."
        ),
    )
    p_bl.add_argument(
        "--volume-density", type=float, default=2.5e-5, metavar="DENSITY",
        dest="volume_density",
        help=(
            "World-volume scatter density per mm (default: 2.5e-5). "
            "Controls visibility of god rays / atmospheric haze. "
            "Try 1e-5 for faint haze, 2.5e-5 for subtle god rays, "
            "5e-5 for visible god rays, 1e-4 for strong fog. "
            "Set to 0 to disable volumetric scattering."
        ),
    )
    p_bl.set_defaults(func=cmd_blender_scene)

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
