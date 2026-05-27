"""
Render an orbit of posed Cycles views from an existing .blend scene.

Run headlessly via:

    blender --background scene.blend --python render_views.py -- '<json-args>'

The scene is already loaded (Blender opens the .blend named on the command
line before executing this script).  We compute the bounding sphere of the
render-visible mesh objects, place ``num_views`` cameras evenly on a sphere
(Fibonacci lattice) looking at the centre, render each with Cycles, and write:

    output_dir/
        images/
            frame_00000.png   (RGBA, transparent background)
            ...
        transforms.json       (nerfstudio / NeRF camera poses)

Why this format
---------------
The cameras are synthetic, so we already know each pose exactly — there is no
need for COLMAP structure-from-motion.  We emit poses in the OpenGL / Blender
camera convention (camera looks down local -Z, +Y up), which is exactly what
``camera.matrix_world`` already is and what nerfstudio-style ``transforms.json``
expects.  A Gaussian-splat trainer such as Brush reads this directly:

    brush output_dir/

A transparent film (alpha background) isolates the detector, which gives a
much cleaner object-centric splat than baking a sky/void into the radiance
field.  Pass ``hide_volume`` to strip the world Volume Scatter (atmospheric
fog) before rendering — volumetrics reconstruct poorly as Gaussians.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))


# ---------------------------------------------------------------------------
# Scene inspection
# ---------------------------------------------------------------------------

def _render_visible_meshes(scene) -> list:
    return [
        obj for obj in scene.objects
        if obj.type == "MESH" and not obj.hide_render
    ]


def _bounding_sphere(objects: list) -> tuple[Vector, float]:
    """World-space (centre, radius) enclosing every vertex bound-box corner."""
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    found = False
    for obj in objects:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            found = True
            for i in range(3):
                mins[i] = min(mins[i], v[i])
                maxs[i] = max(maxs[i], v[i])
    if not found:
        return Vector((0.0, 0.0, 0.0)), 5000.0
    centre = Vector(((mins[0] + maxs[0]) * 0.5,
                     (mins[1] + maxs[1]) * 0.5,
                     (mins[2] + maxs[2]) * 0.5))
    radius = 0.5 * math.sqrt(sum((maxs[i] - mins[i]) ** 2 for i in range(3)))
    return centre, radius


# ---------------------------------------------------------------------------
# Camera placement
# ---------------------------------------------------------------------------

def _fibonacci_directions(n: int, hemisphere: bool, up_axis: int = 1) -> list:
    """
    *n* near-uniform unit directions on a sphere (Fibonacci lattice).

    When *hemisphere* is set, only the half with a non-negative *up_axis*
    component is kept (so the detector is never viewed from straight below).
    """
    dirs = []
    for i in range(n):
        # vertical coordinate from +1 (top) to -1 (bottom)
        v = 1.0 - (i / max(n - 1, 1)) * 2.0
        r = math.sqrt(max(0.0, 1.0 - v * v))
        theta = GOLDEN_ANGLE * i
        a = math.cos(theta) * r
        b = math.sin(theta) * r
        # map (a, v, b) so that *up_axis* carries the vertical coordinate v
        d = [0.0, 0.0, 0.0]
        horiz = [j for j in range(3) if j != up_axis]
        d[up_axis] = v
        d[horiz[0]] = a
        d[horiz[1]] = b
        if hemisphere and d[up_axis] < -1e-6:
            continue
        dirs.append(Vector(d))
    return dirs


def _frame_distance(radius: float, angle_x: float, w: int, h: int,
                    margin: float) -> float:
    """Distance at which a sphere of *radius* fits inside the frame."""
    angle_y = 2.0 * math.atan(math.tan(angle_x * 0.5) * (h / w))
    half_fov = min(angle_x, angle_y) * 0.5
    return radius / math.tan(half_fov) * margin


def _make_camera(scene, fov_deg: float):
    cam_data = bpy.data.cameras.new("SplatOrbitCam")
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.angle = math.radians(fov_deg)
    cam_obj = bpy.data.objects.new("SplatOrbitCam", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    return cam_obj


def _aim(cam_obj, location: Vector, target: Vector) -> None:
    cam_obj.location = location
    cam_obj.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()


# ---------------------------------------------------------------------------
# Render configuration
# ---------------------------------------------------------------------------

def _try_enable_gpu(scene) -> str:
    """Best-effort: enable any available Cycles GPU backend.  Returns label."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = (d.type == backend)
                scene.cycles.device = "GPU"
                return f"{backend} ({len(gpus)} device(s))"
    except Exception:
        pass
    scene.cycles.device = "CPU"
    return "CPU"


def _configure_render(scene, samples: int, w: int, h: int) -> None:
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"


def _strip_world_volume(scene) -> None:
    world = scene.world
    if not (world and world.use_nodes):
        return
    for node in world.node_tree.nodes:
        if node.type == "OUTPUT_WORLD":
            vol = node.inputs.get("Volume")
            if vol:
                for link in list(vol.links):
                    world.node_tree.links.remove(link)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def render_views(
    output_dir: Path,
    num_views: int = 150,
    resolution: int = 1280,
    samples: int = 128,
    fov_deg: float = 50.0,
    margin: float = 1.15,
    hemisphere: bool = False,
    hide_volume: bool = False,
) -> Path:
    scene = bpy.context.scene
    w = h = int(resolution)

    meshes = _render_visible_meshes(scene)
    if not meshes:
        raise RuntimeError("No render-visible mesh objects found in the scene.")
    bpy.context.view_layer.update()
    centre, radius = _bounding_sphere(meshes)
    if radius <= 0.0:
        raise RuntimeError("Degenerate scene bounds (radius <= 0).")

    _configure_render(scene, samples, w, h)
    device = _try_enable_gpu(scene)
    if hide_volume:
        _strip_world_volume(scene)

    cam_obj = _make_camera(scene, fov_deg)
    angle_x = cam_obj.data.angle_x
    distance = _frame_distance(radius, angle_x, w, h, margin)
    directions = _fibonacci_directions(num_views, hemisphere)

    # Intrinsics (square pixels, horizontal sensor fit → fl_x == fl_y).
    fl = (w * 0.5) / math.tan(angle_x * 0.5)

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print(f"[render-views] {len(directions)} views | {w}x{h} | {samples} spp "
          f"| device={device}", flush=True)
    print(f"[render-views] centre={tuple(round(c, 1) for c in centre)} "
          f"radius={radius:.1f} distance={distance:.1f}", flush=True)

    frames = []
    for i, d in enumerate(directions):
        location = centre + d.normalized() * distance
        _aim(cam_obj, location, centre)
        bpy.context.view_layer.update()

        rel_path = f"images/frame_{i:05d}.png"
        scene.render.filepath = str(output_dir / rel_path)
        bpy.ops.render.render(write_still=True)

        frames.append({
            "file_path": rel_path,
            "transform_matrix": [list(row) for row in cam_obj.matrix_world],
        })
        print(f"[render-views] {i + 1}/{len(directions)} -> {rel_path}", flush=True)

    transforms = {
        "camera_model": "OPENCV",
        "camera_angle_x": angle_x,
        "fl_x": fl,
        "fl_y": fl,
        "cx": w * 0.5,
        "cy": h * 0.5,
        "w": w,
        "h": h,
        "frames": frames,
    }
    out_json = output_dir / "transforms.json"
    out_json.write_text(json.dumps(transforms, indent=2))
    print(f"[render-views] wrote {out_json}", flush=True)
    return out_json


if __name__ == "__main__":
    if "--" in sys.argv:
        script_args = sys.argv[sys.argv.index("--") + 1:]
    else:
        script_args = sys.argv[1:]
    if not script_args:
        raise SystemExit("render_views.py: missing JSON argument after '--'")
    kwargs = json.loads(script_args[0])
    kwargs["output_dir"] = Path(kwargs["output_dir"])
    render_views(**kwargs)
