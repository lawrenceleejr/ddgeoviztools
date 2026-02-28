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
import sys
from pathlib import Path


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

    print(f"Splitting {args.gdml_file}")
    print(f"  depth={args.depth}  output-dir={args.output_dir}")
    if detectors:
        print(f"  filter: {detectors}")

    try:
        results = split_gdml(
            input_path=args.gdml_file,
            output_dir=args.output_dir,
            depth=args.depth,
            detectors=detectors,
        )
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    print(f"\nDone — {len(results)} GDML file(s) written to {args.output_dir}/")
    for lv_name, path in results:
        print(f"  {lv_name:50s}  →  {path.name}")
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

    print(f"Converting {args.gdml_file}  →  {output_path}  [{fmt.upper()}]")
    try:
        convert_gdml(
            input_path=args.gdml_file,
            output_path=output_path,
            fmt=fmt,
        )
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    print(f"\nDone — wrote {output_path}")
    return 0


def cmd_split_convert(args: argparse.Namespace) -> int:
    from gdml_splitter import split_gdml
    from gdml_converter import convert_gdml

    fmt = args.format
    output_dir = Path(args.output_dir)
    gdml_dir   = output_dir / "gdml"

    detectors = (
        [d.strip() for d in args.detectors.split(",") if d.strip()]
        if args.detectors
        else None
    )

    # --- Step 1: split ---
    print(f"[1/2] Splitting {args.gdml_file}")
    print(f"      depth={args.depth}  gdml output → {gdml_dir}/")
    try:
        gdml_files = split_gdml(
            input_path=args.gdml_file,
            output_dir=gdml_dir,
            depth=args.depth,
            detectors=detectors,
        )
    except Exception as exc:
        print(f"\nSplit error: {exc}", file=sys.stderr)
        return 1

    print(f"\n      {len(gdml_files)} sub-detector(s) found.\n")

    # --- Step 2: convert each ---
    print(f"[2/2] Converting to {fmt.upper()} → {output_dir}/")
    errors: list[tuple[str, Exception]] = []
    for lv_name, gdml_path in gdml_files:
        out_path = output_dir / f"{gdml_path.stem}.{fmt}"
        print(f"\n  [{lv_name}]")
        try:
            convert_gdml(
                input_path=gdml_path,
                output_path=out_path,
                fmt=fmt,
            )
        except Exception as exc:
            print(f"  [WARN] conversion failed: {exc}", file=sys.stderr)
            errors.append((lv_name, exc))
            if args.fail_fast:
                print("Aborting (--fail-fast).", file=sys.stderr)
                return 1

    n_ok = len(gdml_files) - len(errors)
    print(
        f"\nDone — {n_ok}/{len(gdml_files)} sub-detector(s) converted "
        f"successfully.  Output in {output_dir}/"
    )
    if errors:
        print("\nFailed sub-detectors:", file=sys.stderr)
        for name, exc in errors:
            print(f"  {name}: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_blender_scene(args: argparse.Namespace) -> int:
    from gdml_to_blender import create_blender_scene

    mesh_dir    = Path(args.mesh_dir)
    output_path = Path(args.output)

    # Resolve phi range
    if args.no_phi_cut:
        phi_min = -180.0
        phi_max =  180.0
    else:
        phi_min = args.phi_min if args.phi_min is not None else 0.0
        phi_max = phi_min + args.phi_cut

    print(f"Building Blender scene from {mesh_dir}/")
    print(f"  format={args.format}  output={output_path}")
    if not args.no_phi_cut:
        print(f"  phi cutaway: [{phi_min:.1f}°, {phi_max:.1f}°]")
    else:
        print(f"  phi cutaway: disabled (full detector)")

    try:
        create_blender_scene(
            mesh_dir=mesh_dir,
            output_path=output_path,
            fmt=args.format,
            phi_min=phi_min,
            phi_max=phi_max,
            no_phi_cut=args.no_phi_cut,
            weld_threshold=args.weld_threshold,
        )
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    print(f"\nDone — open {output_path} in Blender.")
    print("  Active camera: Cam_Transverse (XY cross-section, Z=beam into screen).")
    if not args.no_phi_cut:
        print("  Phi cutaway: select 'PhiCutawayControl' → Object Properties")
        print("               → Custom Properties → adjust phi_min / phi_max.")
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
        "--fail-fast", action="store_true",
        help="Abort on the first conversion failure (default: warn and continue).",
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
        "--phi-cut", type=float, default=180.0, metavar="DEGREES",
        help=(
            "Angular width of the visible phi sector in degrees (default: 180). "
            "phi=atan2(Y,X); Z=beam. "
            "180 = upper half [0°,180°]. 360 = full detector. "
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
    p_bl.set_defaults(func=cmd_blender_scene)

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
