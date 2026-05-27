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


def _scene_bounds(objects: list) -> tuple[Vector, float, Vector, Vector]:
    """World-space (centre, bounding-sphere radius, aabb-min, aabb-max)."""
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
        return (Vector((0.0, 0.0, 0.0)), 5000.0,
                Vector((-5000.0,) * 3), Vector((5000.0,) * 3))
    centre = Vector(((mins[0] + maxs[0]) * 0.5,
                     (mins[1] + maxs[1]) * 0.5,
                     (mins[2] + maxs[2]) * 0.5))
    radius = 0.5 * math.sqrt(sum((maxs[i] - mins[i]) ** 2 for i in range(3)))
    return centre, radius, Vector(mins), Vector(maxs)


def _read_cut_sector(scene, cli_min, cli_max) -> tuple[float, float]:
    """
    Opening sector [phi_min, phi_max] (degrees) that the cutaway removed.

    Explicit CLI values win.  Otherwise read the PhiCutawayControl empty's
    custom properties (set by the blender-scene builder).  Final fallback is
    the documented default sector [0, 90].
    """
    if cli_min is not None and cli_max is not None:
        return float(cli_min), float(cli_max)
    ctrl = bpy.data.objects.get("PhiCutawayControl")
    if ctrl is not None and "phi_min" in ctrl.keys() and "phi_max" in ctrl.keys():
        return float(ctrl["phi_min"]), float(ctrl["phi_max"])
    return (0.0 if cli_min is None else float(cli_min),
            90.0 if cli_max is None else float(cli_max))


def _phi_world_dir(phi_deg: float) -> Vector:
    """
    Transverse (beam-perpendicular) world direction for cut angle *phi*.

    Scene convention (see gdml_to_blender / README): beam = world X, up =
    world Y, and phi=0 -> +Y, phi=90 -> +Z, so the direction lies in the
    Y-Z plane: (0, cos phi, sin phi).
    """
    p = math.radians(phi_deg)
    return Vector((0.0, math.cos(p), math.sin(p)))


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


def _aim(cam_obj, location: Vector, target: Vector, up: str = "Y") -> None:
    cam_obj.location = location
    cam_obj.rotation_euler = (target - location).to_track_quat("-Z", up).to_euler()


def _exterior_poses(centre: Vector, distance: float, num_views: int,
                    hemisphere: bool) -> list:
    """(location, target, up) tuples on the orbit sphere, all aimed at centre."""
    return [(centre + d.normalized() * distance, centre, "Y")
            for d in _fibonacci_directions(num_views, hemisphere)]


def _interior_poses(centre: Vector, radius: float, aabb_min: Vector,
                    aabb_max: Vector, phi_min: float, phi_max: float,
                    num_views: int, radius_frac: float) -> list:
    """
    Cameras that sit *inside* the open cutaway wedge and look radially inward
    at the core, so the splat captures the revealed inner detectors.

    Each camera is placed at a transverse angle within [phi_min, phi_max]
    (inset from the cut planes so it stays clear of solid geometry) and swept
    along the beam (world X), aiming at the on-axis point at its own beam
    offset — i.e. looking straight in at that cross-section.  Up = beam (X) so
    the inward-looking views don't gimbal when the sightline nears world Y.
    """
    if num_views <= 0 or phi_max <= phi_min:
        return []
    beam = Vector((1.0, 0.0, 0.0))
    half_len = 0.5 * (aabb_max.x - aabb_min.x)
    cam_radius = radius * radius_frac
    span = phi_max - phi_min
    inset = 0.15 * span                     # keep cameras off the cut planes
    lo, hi = phi_min + inset, phi_max - inset
    poses = []
    for i in range(num_views):
        # azimuth: golden-ratio walk across the (inset) opening
        phi = lo + ((i * 0.618033988749895) % 1.0) * (hi - lo)
        # beam sweep: even pass from -0.4L to +0.4L of detector length
        t = (i + 0.5) / num_views
        x_off = (t * 2.0 - 1.0) * 0.4 * half_len
        target = centre + beam * x_off
        location = target + _phi_world_dir(phi) * cam_radius
        poses.append((location, target, "X"))
    return poses


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
    interior_views: int = 0,
    interior_radius: float = 0.55,
    cut_phi_min: float | None = None,
    cut_phi_max: float | None = None,
) -> Path:
    scene = bpy.context.scene
    w = h = int(resolution)

    meshes = _render_visible_meshes(scene)
    if not meshes:
        raise RuntimeError("No render-visible mesh objects found in the scene.")
    bpy.context.view_layer.update()
    centre, radius, aabb_min, aabb_max = _scene_bounds(meshes)
    if radius <= 0.0:
        raise RuntimeError("Degenerate scene bounds (radius <= 0).")

    _configure_render(scene, samples, w, h)
    device = _try_enable_gpu(scene)
    if hide_volume:
        _strip_world_volume(scene)

    cam_obj = _make_camera(scene, fov_deg)
    angle_x = cam_obj.data.angle_x
    distance = _frame_distance(radius, angle_x, w, h, margin)

    # Intrinsics (square pixels, horizontal sensor fit → fl_x == fl_y).
    fl = (w * 0.5) / math.tan(angle_x * 0.5)

    poses = _exterior_poses(centre, distance, num_views, hemisphere)
    if interior_views > 0:
        phi_min, phi_max = _read_cut_sector(scene, cut_phi_min, cut_phi_max)
        poses += _interior_poses(centre, radius, aabb_min, aabb_max,
                                 phi_min, phi_max, interior_views, interior_radius)
        print(f"[render-views] interior: {interior_views} views through cut "
              f"sector [{phi_min:.0f}°, {phi_max:.0f}°] at "
              f"{interior_radius:.2f}×radius", flush=True)

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print(f"[render-views] {len(poses)} views | {w}x{h} | {samples} spp "
          f"| device={device}", flush=True)
    print(f"[render-views] centre={tuple(round(c, 1) for c in centre)} "
          f"radius={radius:.1f} distance={distance:.1f}", flush=True)

    frames = []
    for i, (location, target, up) in enumerate(poses):
        _aim(cam_obj, location, target, up)
        bpy.context.view_layer.update()

        rel_path = f"images/frame_{i:05d}.png"
        scene.render.filepath = str(output_dir / rel_path)
        bpy.ops.render.render(write_still=True)

        frames.append({
            "file_path": rel_path,
            "transform_matrix": [list(row) for row in cam_obj.matrix_world],
        })
        print(f"[render-views] {i + 1}/{len(poses)} -> {rel_path}", flush=True)

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
