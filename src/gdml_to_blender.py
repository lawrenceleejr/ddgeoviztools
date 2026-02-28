"""
Create a Blender scene (.blend) from per-sub-detector mesh files.

Features
--------
- Reads OBJ / GLTF / VTP mesh files produced by ddgeoviztools' convert step.
- Cleans up duplicate vertices (trimesh process=True + Weld modifier).
- Assigns physics-inspired materials (steel, brass, copper, matte variants).
- Adds a phi-cutaway Geometry Nodes modifier (adjustable via PhiCutawayControl
  empty object — change one property, all sub-detectors update).
- Sets up the scene with collider physics convention: Z = beam, Y = sky
  (right-handed; geometry is imported as-is from GDML/VTK coordinates).
- Adds pre-positioned orthographic cameras for the two standard HEP views:
    Cam_Transverse  — looking along −Z, sees XY cross-section
    Cam_Side        — looking along −X, sees ZY (beam = horizontal, Y = up)
    Cam_Perspective — 3/4 overview
- Saves as a .blend file readable by any Blender 4.x installation.
"""
from __future__ import annotations

import math
import sys
from itertools import cycle
from pathlib import Path

import bpy
import numpy as np
import trimesh
from mathutils import Vector

# ---------------------------------------------------------------------------
# Material palette
# ---------------------------------------------------------------------------

_PALETTE = [
    # (name,               base_RGB,              metallic, roughness)
    ("Steel",            (0.65, 0.67, 0.70),       0.95,     0.20),
    ("Brushed_Steel",    (0.58, 0.60, 0.63),       0.90,     0.45),
    ("Dark_Steel",       (0.30, 0.32, 0.35),       0.85,     0.35),
    ("Brass",            (0.72, 0.55, 0.20),       0.95,     0.20),
    ("Copper",           (0.72, 0.40, 0.25),       0.95,     0.25),
    ("Matte_Gray",       (0.45, 0.45, 0.48),       0.00,     0.85),
    ("Matte_Dark",       (0.20, 0.20, 0.22),       0.00,     0.90),
    ("Brushed_Aluminum", (0.78, 0.79, 0.80),       0.95,     0.35),
    ("Dark_Brass",       (0.55, 0.42, 0.15),       0.90,     0.30),
    ("Oxidized_Copper",  (0.25, 0.50, 0.40),       0.60,     0.65),
]


def _make_material(name: str, color_rgb: tuple, metallic: float, roughness: float):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color_rgb, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    # "Specular IOR Level" in Blender 4.x; "Specular" in 3.x
    for key in ("Specular IOR Level", "Specular"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.5
            break
    return mat


def _pre_create_materials() -> list:
    """Create all palette materials up-front and return them."""
    return [_make_material(*entry) for entry in _PALETTE]


# ---------------------------------------------------------------------------
# Mesh loading with duplicate-vertex cleanup
# ---------------------------------------------------------------------------

def _load_mesh(filepath: Path, name: str):
    """
    Read a mesh file with trimesh, merge duplicate vertices and remove
    degenerate faces, then create a bpy Mesh object.

    Returns the new bpy Object.
    """
    # trimesh process=True: merges identical vertices, removes degenerate faces
    raw = trimesh.load(str(filepath), force="mesh", process=True)

    if isinstance(raw, trimesh.Scene):
        # Flatten a multi-mesh scene into one mesh
        meshes = list(raw.geometry.values())
        if not meshes:
            raise ValueError(f"No geometry found in {filepath}")
        raw = trimesh.util.concatenate(meshes)
        raw = trimesh.Trimesh(raw.vertices, raw.faces, process=True)

    verts = raw.vertices.tolist()   # list of [x, y, z]
    faces = raw.faces.tolist()      # list of [i, j, k]

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()

    obj = bpy.data.objects.new(name, me)
    bpy.data.scenes[0].collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# Geometry simplification — Weld modifier (merges near-duplicate vertices)
# ---------------------------------------------------------------------------

def _add_weld(obj, threshold: float = 1e-4):
    """
    Add a Weld modifier that merges vertices within `threshold` distance.
    For GDML-derived meshes the threshold is in mm (GDML native units).
    1e-4 mm = 0.1 µm — safely sub-tolerance for any realistic geometry.
    """
    mod = obj.modifiers.new("Weld", "WELD")
    mod.merge_threshold = threshold
    return mod


# ---------------------------------------------------------------------------
# Phi-cutaway Geometry Node group
# ---------------------------------------------------------------------------

def _phi_cutaway_node_group(phi_min_default: float, phi_max_default: float):
    """
    Build (or retrieve) the shared 'PhiCutaway' geometry node group.

    Node graph
    ----------
    Position → SeparateXYZ
                 Y, X  → Math(ARCTAN2) → Math(DEGREES) → phi_deg
    phi_deg + Phi Min → Math(GREATER_THAN) → gt
    phi_deg + Phi Max → Math(LESS_THAN)    → lt
    Math(MULTIPLY, gt, lt)        → inside   (1.0 if in range)
    Math(SUBTRACT, 1.0, inside)   → outside  (1.0 = delete this face)
    Merge by Distance             → (weld any remaining seam duplicates)
    Delete Geometry (FACE domain, selection=outside)

    Convention
    ----------
    phi = atan2(Y, X) in degrees, range [-180, 180].
    Z = beam → transverse plane is XY.
    phi=0  → +X (horizontal right)
    phi=90 → +Y (up, towards sky)

    Default phi_min=0, phi_max=180 shows the upper half of the detector.
    """
    NG_NAME = "PhiCutaway"
    if NG_NAME in bpy.data.node_groups:
        return bpy.data.node_groups[NG_NAME]

    ng    = bpy.data.node_groups.new(NG_NAME, "GeometryNodeTree")
    nodes = ng.nodes
    links = ng.links

    # ---- Interface (Blender 4.0 API) ----
    ng.interface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
    s_min = ng.interface.new_socket("Phi Min", in_out="INPUT",  socket_type="NodeSocketFloat")
    s_max = ng.interface.new_socket("Phi Max", in_out="INPUT",  socket_type="NodeSocketFloat")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    s_min.default_value = phi_min_default
    s_max.default_value = phi_max_default

    # ---- Nodes ----
    def N(bl_type, x=0, y=0):
        n = nodes.new(bl_type)
        n.location = (x, y)
        return n

    g_in  = N("NodeGroupInput",              -700,    0)
    g_out = N("NodeGroupOutput",              700,    0)

    # Vertex position → atan2(Y, X) → degrees
    pos   = N("GeometryNodeInputPosition",   -500, -120)
    sep   = N("ShaderNodeSeparateXYZ",        -300, -120)

    atan2 = N("ShaderNodeMath",              -100, -120)
    atan2.operation = "ARCTAN2"
    atan2.label = "atan2(Y,X)"

    todeg = N("ShaderNodeMath",               100, -120)
    todeg.operation = "DEGREES"
    todeg.label = "to degrees"

    # Range test: gt * lt = 1.0 iff inside
    gt = N("ShaderNodeMath",                  300,   80)
    gt.operation = "GREATER_THAN"
    gt.label = "phi > phi_min"

    lt = N("ShaderNodeMath",                  300,  -80)
    lt.operation = "LESS_THAN"
    lt.label = "phi < phi_max"

    mul = N("ShaderNodeMath",                 460,    0)
    mul.operation = "MULTIPLY"
    mul.label = "inside"

    sub = N("ShaderNodeMath",                 560,    0)
    sub.operation = "SUBTRACT"
    sub.label = "outside = 1 - inside"
    sub.inputs[0].default_value = 1.0   # minuend; inside connects to inputs[1]

    # Merge seam duplicates before the cut
    merge = N("GeometryNodeMergeByDistance",  -500,  100)
    merge.inputs["Distance"].default_value = 1e-4
    merge.label = "Weld seam duplicates"

    # Delete faces outside phi range
    delete = N("GeometryNodeDeleteGeometry",   620,    0)
    delete.domain = "FACE"
    delete.mode   = "ALL"

    # ---- Wiring ----
    # Geometry pass-through via merge-by-distance first
    links.new(g_in.outputs["Geometry"],   merge.inputs["Geometry"])

    # Position field chain
    links.new(pos.outputs["Position"],    sep.inputs["Vector"])
    links.new(sep.outputs["Y"],           atan2.inputs[0])   # Y is first arg
    links.new(sep.outputs["X"],           atan2.inputs[1])   # X is second
    links.new(atan2.outputs["Value"],     todeg.inputs["Value"])

    # Phi-range tests
    links.new(todeg.outputs["Value"],     gt.inputs[0])
    links.new(g_in.outputs["Phi Min"],    gt.inputs[1])
    links.new(todeg.outputs["Value"],     lt.inputs[0])
    links.new(g_in.outputs["Phi Max"],    lt.inputs[1])

    # Combine and invert
    links.new(gt.outputs["Value"],        mul.inputs[0])
    links.new(lt.outputs["Value"],        mul.inputs[1])
    links.new(mul.outputs["Value"],       sub.inputs[1])

    # Delete geometry
    links.new(merge.outputs["Geometry"],  delete.inputs["Geometry"])
    links.new(sub.outputs["Value"],       delete.inputs["Selection"])
    links.new(delete.outputs["Geometry"], g_out.inputs["Geometry"])

    return ng


def _add_phi_cutaway(obj, ng, phi_min: float, phi_max: float, ctrl_obj):
    """
    Add the PhiCutaway GN modifier to obj and wire drivers from ctrl_obj.
    """
    mod = obj.modifiers.new("PhiCutaway", "NODES")
    mod.node_group = ng

    # Identify socket identifiers by name
    id_min = id_max = None
    for item in ng.interface.items_tree:
        if getattr(item, "item_type", None) == "SOCKET" and item.in_out == "INPUT":
            if item.name == "Phi Min":
                id_min = item.identifier
            elif item.name == "Phi Max":
                id_max = item.identifier

    for identifier, prop_name, default in (
        (id_min, "phi_min", phi_min),
        (id_max, "phi_max", phi_max),
    ):
        if identifier is None:
            continue
        mod[identifier] = default

        try:
            fc  = mod.driver_add(f'["{identifier}"]')
            drv = fc.driver
            drv.type = "SCRIPTED"
            var = drv.variables.new()
            var.name = "val"
            var.type = "SINGLE_PROP"
            var.targets[0].id        = ctrl_obj
            var.targets[0].data_path = f'["{prop_name}"]'
            drv.expression = "val"
        except Exception:
            pass  # drivers are cosmetic; don't abort scene creation


# ---------------------------------------------------------------------------
# Scene utilities
# ---------------------------------------------------------------------------

def _clear_scene():
    """Remove every default object (cube, light, camera)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _setup_units():
    scene = bpy.data.scenes[0]
    scene.unit_settings.system       = "METRIC"
    scene.unit_settings.scale_length = 0.001   # 1 Blender unit = 1 mm
    scene.unit_settings.length_unit  = "MILLIMETERS"


def _add_sun(name: str, direction: tuple, energy: float):
    light_data = bpy.data.lights.new(name=name, type="SUN")
    light_data.energy = energy
    light_obj = bpy.data.objects.new(name, light_data)
    bpy.data.scenes[0].collection.objects.link(light_obj)
    # Point sun in direction by computing rotation from (0,0,-1) → direction
    fwd = Vector(direction).normalized()
    light_obj.rotation_euler = fwd.to_track_quat("-Z", "Y").to_euler()
    return light_obj


def _make_camera(name: str, location: tuple, target: tuple,
                 ortho: bool = True, ortho_scale: float = 10000.0):
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO" if ortho else "PERSP"
    if ortho:
        cam_data.ortho_scale = ortho_scale
    else:
        cam_data.lens = 50

    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.data.scenes[0].collection.objects.link(cam_obj)
    cam_obj.location = Vector(location)

    direction = (Vector(target) - Vector(location)).normalized()
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam_obj


def _scene_bounds(objects: list) -> tuple[float, float, float]:
    """Return (x_max, y_max, z_max) of the combined bounding box (in mm)."""
    xs, ys, zs = [], [], []
    for obj in objects:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            xs.append(v.x); ys.append(v.y); zs.append(v.z)
    if not xs:
        return 5000.0, 5000.0, 5000.0
    return max(abs(x) for x in xs), max(abs(y) for y in ys), max(abs(z) for z in zs)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def create_blender_scene(
    mesh_dir:    Path,
    output_path: Path,
    fmt:         str   = "gltf",
    phi_min:     float = 0.0,
    phi_max:     float = 180.0,
    no_phi_cut:  bool  = False,
    weld_threshold: float = 1e-4,
) -> Path:
    """
    Build and save a Blender scene from a directory of mesh files.

    Parameters
    ----------
    mesh_dir     : directory containing *.{fmt} files (one per sub-detector)
    output_path  : where to write the .blend file
    fmt          : input mesh format ('gltf', 'glb', 'obj', 'vtp')
    phi_min      : initial phi cutaway minimum (degrees), default 0
    phi_max      : initial phi cutaway maximum (degrees), default 180
    no_phi_cut   : if True, skip phi-cutaway modifier entirely
    weld_threshold : distance for Weld modifier in mm (default 1e-4)
    """
    mesh_dir    = Path(mesh_dir)
    output_path = Path(output_path)

    # Collect mesh files (try requested format, then common fallbacks)
    formats_to_try = [fmt] + [f for f in ("gltf", "glb", "obj", "vtp") if f != fmt]
    mesh_files: list[Path] = []
    used_fmt = fmt
    for f in formats_to_try:
        found = sorted(mesh_dir.glob(f"*.{f}"))
        if found:
            mesh_files = found
            used_fmt = f
            break

    if not mesh_files:
        raise FileNotFoundError(
            f"No mesh files found in {mesh_dir}. "
            f"Run 'convert' or 'split-convert' first."
        )

    print(f"  Found {len(mesh_files)} {used_fmt.upper()} file(s) in {mesh_dir}")

    # ---- Initialize Blender scene ----
    _clear_scene()
    _setup_units()

    # ---- Pre-create materials ----
    materials = _pre_create_materials()
    mat_cycle = cycle(materials)

    # ---- Phi-cutaway control object ----
    ctrl = None
    ng   = None
    if not no_phi_cut:
        ctrl = bpy.data.objects.new("PhiCutawayControl", None)  # Empty
        bpy.data.scenes[0].collection.objects.link(ctrl)
        ctrl["phi_min"] = float(phi_min)
        ctrl["phi_max"] = float(phi_max)
        try:
            ctrl.id_properties_ui("phi_min").update(
                min=-180.0, max=360.0,
                description="Phi cutaway minimum (degrees). atan2(Y,X), Z=beam."
            )
            ctrl.id_properties_ui("phi_max").update(
                min=-180.0, max=360.0,
                description="Phi cutaway maximum (degrees)."
            )
        except Exception:
            pass
        ng = _phi_cutaway_node_group(phi_min, phi_max)

    # ---- Load each mesh ----
    loaded_objects: list = []
    for mesh_path in mesh_files:
        name = mesh_path.stem
        print(f"  Loading {mesh_path.name} ...")
        try:
            obj = _load_mesh(mesh_path, name)
        except Exception as exc:
            print(f"  [WARN] Could not load {mesh_path.name}: {exc}", file=sys.stderr)
            continue

        # Material
        mat = next(mat_cycle)
        obj.data.materials.append(mat)

        # Weld modifier (mesh cleanup — merges near-duplicate vertices)
        _add_weld(obj, threshold=weld_threshold)

        # Phi cutaway
        if not no_phi_cut and ng is not None and ctrl is not None:
            _add_phi_cutaway(obj, ng, phi_min, phi_max, ctrl)

        loaded_objects.append(obj)
        print(f"    → {len(obj.data.vertices)} verts, {len(obj.data.polygons)} faces"
              f"  material: {mat.name}")

    if not loaded_objects:
        raise RuntimeError("No mesh files could be loaded.")

    # ---- Compute scene bounds for camera placement ----
    x_max, y_max, z_max = _scene_bounds(loaded_objects)
    r_trans = max(x_max, y_max) * 1.6   # radius for transverse camera (XY)
    r_side  = max(z_max, y_max) * 1.6   # radius for side camera (ZY)
    r_persp = max(x_max, y_max, z_max) * 2.2

    ortho_trans = max(x_max, y_max) * 2.2   # orthographic scale in mm
    ortho_side  = max(z_max, y_max) * 2.2

    # ---- Cameras ----
    # Transverse: camera on +Z axis looking toward origin
    #   → sees XY plane: X=right, Y=up, Z(beam) into screen
    cam_trans = _make_camera(
        "Cam_Transverse",
        location=(0, 0, r_trans),
        target=(0, 0, 0),
        ortho=True,
        ortho_scale=ortho_trans,
    )

    # Side: camera on +X axis looking toward origin
    #   → sees ZY plane: Z(beam)=horizontal-right, Y=up
    _make_camera(
        "Cam_Side",
        location=(r_side, 0, 0),
        target=(0, 0, 0),
        ortho=True,
        ortho_scale=ortho_side,
    )

    # Perspective overview from 3/4 angle
    _make_camera(
        "Cam_Perspective",
        location=(r_persp * 0.55, -r_persp * 0.75, r_persp * 0.35),
        target=(0, 0, 0),
        ortho=False,
    )

    # Set default active camera to transverse view
    bpy.data.scenes[0].camera = cam_trans

    # ---- Lighting ----
    # Key light (from upper-right-front in physics coords)
    _add_sun("Sun_Key",  direction=( 0.5, -0.5,  1.0), energy=3.0)
    # Fill light (softer, from upper-left)
    _add_sun("Sun_Fill", direction=(-0.8,  0.6,  0.4), energy=1.5)

    # ---- Save ----
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    print(f"\n  Saved: {output_path}")
    print(f"  Objects: {len(loaded_objects)}")
    print(f"  Active camera: Cam_Transverse (XY cross-section, Z=beam into screen)")
    if not no_phi_cut:
        print(f"  Phi cutaway: [{phi_min:.0f}°, {phi_max:.0f}°]  "
              f"— adjust via PhiCutawayControl → Custom Properties")

    return output_path
