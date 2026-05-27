"""
render_cameras.py — render every stationary camera in a .blend to a still image.

Run inside Blender's bundled Python:

    blender --background scene.blend --python scripts/render_cameras.py -- \
        --out renders/ [--samples N] [--width W] [--height H] \
        [--engine CYCLES|BLENDER_EEVEE_NEXT] [--device CPU|GPU]

"Stationary" means a camera object with no animated transform — i.e. the
fixed HEP views (Cam_Transverse, Cam_Side, Cam_Perspective). The animated
hero camera (Cam_Hero) is skipped.

Built for headless CI: defaults to low resolution / sample count and CPU
rendering so it completes without a GPU. Motion blur is disabled (it only
matters for the animated camera and is expensive on a single frame).
"""
import argparse
import sys
from pathlib import Path

import bpy


def parse_args(argv):
    p = argparse.ArgumentParser(prog="render_cameras.py")
    p.add_argument("--out", required=True, help="Output directory for PNGs.")
    p.add_argument("--samples", type=int, default=32, help="Cycles samples.")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--engine", default="CYCLES")
    p.add_argument("--device", default="CPU", choices=["CPU", "GPU"])
    return p.parse_args(argv)


def is_stationary(obj):
    """A camera is stationary if it has no transform animation f-curves."""
    ad = obj.animation_data
    if ad is not None and ad.action is not None and len(ad.action.fcurves) > 0:
        return False
    return True


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene

    scene.render.engine = args.engine
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_motion_blur = False

    if args.engine == "CYCLES":
        scene.cycles.device = args.device
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = True

    cameras = [o for o in scene.objects if o.type == "CAMERA" and is_stationary(o)]
    cameras.sort(key=lambda o: o.name)

    if not cameras:
        print("render_cameras.py: ERROR — no stationary cameras found", flush=True)
        sys.exit(1)

    print(f"render_cameras.py: rendering {len(cameras)} stationary camera(s) at "
          f"{args.width}x{args.height}, {args.engine}, "
          f"{args.samples if args.engine == 'CYCLES' else 'n/a'} samples", flush=True)

    rendered = []
    for cam in cameras:
        scene.camera = cam
        out_path = out_dir / f"{cam.name}.png"
        scene.render.filepath = str(out_path)
        print(f"  [RENDER] {cam.name} -> {out_path}", flush=True)
        bpy.ops.render.render(write_still=True)
        if not out_path.exists():
            print(f"render_cameras.py: ERROR — {cam.name} produced no output file",
                  flush=True)
            sys.exit(1)
        rendered.append(out_path)

    print(f"render_cameras.py: done — {len(rendered)} image(s) written to {out_dir}",
          flush=True)


if __name__ == "__main__":
    main()
