#!/usr/bin/env python3
"""
blend_to_ue5.py — Export all sub-detector meshes from a Blender file to GLTF + manifest.json.

Usage (headless Blender):
    blender --background detector.blend --python blend_to_ue5.py -- --output-dir /tmp/ue5_meshes/

Output:
    <output_dir>/
        ECalBarrel.gltf
        HCalBarrel.gltf
        ...
        manifest.json

manifest.json schema:
{
  "sub_detectors": [
    {
      "name": "ECalBarrel",
      "gltf_file": "ECalBarrel.glb",
      "base_color": [r, g, b, a],
      "metallic": 0.10,
      "roughness": 0.35,
      "actor_tags": ["ECalBarrel"]
    },
    ...
  ],
  "lights": [
    {
      "name": "Key_Amber",
      "type": "AREA",               # AREA | SUN | POINT | SPOT
      "location_m": [x, y, z],      # Blender world space, metres, Z-up
      "rotation_euler": [rx, ry, rz],  # radians, XYZ
      "direction": [dx, dy, dz],    # world-space forward (light local -Z), normalised
      "energy": 1000.0,             # Watts (AREA/POINT/SPOT) or W/m^2 (SUN)
      "color": [r, g, b],           # linear RGB tint
      "temperature_k": 3200,        # Kelvin if a Blackbody node drives the colour, else null
      "size": 2.0,                  # AREA: panel width  (metres)
      "size_y": 1.2,                # AREA: panel height (metres; == size for SQUARE/DISK)
      "shape": "RECTANGLE",         # AREA shape
      "spot_size_rad": 1.04,        # SPOT: full cone angle (radians)
      "spot_blend": 0.15            # SPOT: edge softness 0..1
    },
    ...
  ],
  "cameras": [
    { "name": "Perspective", "type": "PERSP", "location_m": [x,y,z],
      "rotation_euler": [rx,ry,rz], "lens_mm": 50.0, "sensor_width_mm": 36.0,
      "dof": {"use_dof": true, "fstop": 2.8, "focus_distance_m": 6.0} }
  ]
}

Notes:
- Meshes: iterates the "Detector" Blender collection (created by gdml_to_blender.py),
  applies all modifiers (bevel, etc.) before export. Phi cutaway is already baked into
  the mesh geometry, so it transfers automatically — no extra handling needed.
- GLTF export: Y-forward convention corrected to UE5 Z-up via export_yup=True.
- Material params read from Principled BSDF node on each object's first material slot.
- Lights/cameras: exported as NUMERIC TRANSFORMS in Blender world space (metres, Z-up),
  NOT through glTF. They are *not* re-axised by export_yup. The consumer
  (Tools/ue5_build_content.py) applies the matching Blender->UE basis (LIGHT_BASIS) so the
  spawned UE light actors line up with the export_yup meshes. Keep the two scripts in sync:
  if the mesh export axis convention changes, update LIGHT_BASIS in ue5_build_content.py.
"""

import sys
import json
import os
import argparse
from pathlib import Path


def parse_args():
    """Parse args that appear after the '--' separator in Blender's argv."""
    try:
        sep_idx = sys.argv.index("--")
    except ValueError:
        sep_idx = len(sys.argv)
    own_args = sys.argv[sep_idx + 1:]

    parser = argparse.ArgumentParser(
        description="Export Blender 'Detector' collection to per-object GLTF + manifest.json"
    )
    parser.add_argument("--output-dir", required=True,
                        help="Directory to write GLTF files and manifest.json")
    parser.add_argument("--collection", default="Detector",
                        help="Blender collection name to export (default: Detector)")
    parser.add_argument("--no-lights", action="store_true",
                        help="Skip exporting the Blender light rig to the manifest")
    parser.add_argument("--no-cameras", action="store_true",
                        help="Skip exporting Blender cameras to the manifest")
    return parser.parse_args(own_args)


def get_principled_bsdf_params(material):
    """
    Extract base_color, metallic, roughness from a Principled BSDF node.
    Returns defaults if node not found.
    """
    base_color = [0.5, 0.5, 0.5, 1.0]
    metallic   = 0.5
    roughness  = 0.5

    if material is None or material.node_tree is None:
        return base_color, metallic, roughness

    nodes = material.node_tree.nodes
    pbsdf = nodes.get("Principled BSDF")
    if pbsdf is None:
        # Try finding by type
        for node in nodes:
            if node.type == "BSDF_PRINCIPLED":
                pbsdf = node
                break

    if pbsdf is None:
        return base_color, metallic, roughness

    try:
        bc = pbsdf.inputs["Base Color"].default_value
        base_color = [round(bc[0], 4), round(bc[1], 4), round(bc[2], 4), round(bc[3], 4)]
    except (KeyError, IndexError):
        pass

    try:
        metallic = round(float(pbsdf.inputs["Metallic"].default_value), 4)
    except (KeyError, TypeError):
        pass

    try:
        roughness = round(float(pbsdf.inputs["Roughness"].default_value), 4)
    except (KeyError, TypeError):
        pass

    return base_color, metallic, roughness


def apply_modifiers(obj, depsgraph):
    """Apply all modifiers on obj destructively, replacing mesh data."""
    import bpy

    # Evaluate the object with modifiers applied
    obj_eval = obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()

    # Replace the original mesh data
    obj.data = obj.data.copy()
    obj.data.clear_geometry()
    obj.data.from_pydata(
        [v.co[:] for v in mesh_eval.vertices],
        [],
        [p.vertices[:] for p in mesh_eval.polygons],
    )
    obj.data.update()

    # Release evaluated mesh
    obj_eval.to_mesh_clear()

    # Remove all modifiers now that geometry is baked
    obj.modifiers.clear()


def export_object_as_gltf(obj, output_path: Path, context):
    """Select only this object, apply modifiers, export as GLTF 2.0."""
    import bpy

    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # Apply modifiers via evaluated mesh
    depsgraph = bpy.context.evaluated_depsgraph_get()
    apply_modifiers(obj, depsgraph)

    # Export selection as GLTF
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format='GLB',          # binary glTF — single .glb file (matches gltf_file in manifest)
        use_selection=True,
        export_apply=True,
        export_materials='EXPORT',
        export_normals=True,
        export_texcoords=True,
        export_yup=True,              # Y-up → UE5 expects Z-up; Blender→UE5 standard
        export_animations=False,
        export_morph=False,
        export_skins=False,
        check_existing=False,
    )


def _light_temperature(light):
    """
    Return the Blackbody colour temperature (Kelvin) driving a light, or None.

    gdml_to_blender.py tints lights either via a ShaderNodeBlackbody node feeding the
    emission colour (Blender 3.x/4.x) or via a native temperature attribute (Blender 5.0+).
    Check both.
    """
    # Native attribute (Blender 5.0+: light.temperature when use_temperature is on)
    if getattr(light, "use_temperature", False) and hasattr(light, "temperature"):
        try:
            return round(float(light.temperature), 1)
        except (TypeError, ValueError):
            pass
    # Blackbody node in the light's shader tree
    if getattr(light, "use_nodes", False) and light.node_tree is not None:
        for node in light.node_tree.nodes:
            if node.bl_idname == "ShaderNodeBlackbody":
                try:
                    return round(float(node.inputs["Temperature"].default_value), 1)
                except (KeyError, TypeError, ValueError):
                    pass
    return None


def _world_forward(obj):
    """World-space forward direction of a light/camera (local -Z), normalised."""
    from mathutils import Vector
    d = (obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    return [round(d.x, 6), round(d.y, 6), round(d.z, 6)]


def light_to_entry(obj):
    """Build a manifest light entry from a Blender LIGHT object (world space, metres)."""
    lamp = obj.data
    loc = obj.matrix_world.translation
    entry = {
        "name":           obj.name,
        "type":           lamp.type,                       # POINT | SUN | SPOT | AREA
        "location_m":     [round(loc.x, 5), round(loc.y, 5), round(loc.z, 5)],
        "rotation_euler": [round(a, 6) for a in obj.rotation_euler],
        "direction":      _world_forward(obj),
        "energy":         round(float(lamp.energy), 4),    # W (POINT/SPOT/AREA), W/m^2 (SUN)
        "color":          [round(c, 4) for c in lamp.color],
        "temperature_k":  _light_temperature(lamp),
    }
    if lamp.type == "AREA":
        entry["size"]   = round(float(lamp.size), 5)
        entry["size_y"] = round(float(getattr(lamp, "size_y", lamp.size)), 5)
        entry["shape"]  = lamp.shape
    elif lamp.type == "SPOT":
        entry["spot_size_rad"] = round(float(lamp.spot_size), 6)
        entry["spot_blend"]    = round(float(lamp.spot_blend), 4)
    return entry


def camera_to_entry(obj):
    """Build a manifest camera entry from a Blender CAMERA object (world space, metres)."""
    cam = obj.data
    loc = obj.matrix_world.translation
    dof = getattr(cam, "dof", None)
    entry = {
        "name":            obj.name,
        "type":            cam.type,                        # PERSP | ORTHO | PANO
        "location_m":      [round(loc.x, 5), round(loc.y, 5), round(loc.z, 5)],
        "rotation_euler":  [round(a, 6) for a in obj.rotation_euler],
        "direction":       _world_forward(obj),
        "lens_mm":         round(float(cam.lens), 4),
        "sensor_width_mm": round(float(cam.sensor_width), 4),
    }
    if cam.type == "ORTHO":
        entry["ortho_scale"] = round(float(cam.ortho_scale), 4)
    if dof is not None:
        entry["dof"] = {
            "use_dof":          bool(dof.use_dof),
            "fstop":            round(float(dof.aperture_fstop), 4),
            "focus_distance_m": round(float(dof.focus_distance), 5),
        }
    return entry


def export_lights():
    """Export all LIGHT objects in the scene to manifest entries."""
    import bpy
    lights = [light_to_entry(o) for o in bpy.data.objects if o.type == "LIGHT"]
    print(f"Found {len(lights)} light(s)")
    return lights


def export_cameras():
    """Export all CAMERA objects in the scene to manifest entries."""
    import bpy
    cameras = [camera_to_entry(o) for o in bpy.data.objects if o.type == "CAMERA"]
    print(f"Found {len(cameras)} camera(s)")
    return cameras


def main():
    import bpy

    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    collection_name = args.collection

    # Find the target collection
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        print(f"ERROR: Collection '{collection_name}' not found in scene.", file=sys.stderr)
        print("Available collections:", [c.name for c in bpy.data.collections], file=sys.stderr)
        sys.exit(1)

    objects = [obj for obj in collection.objects if obj.type == 'MESH']
    print(f"Found {len(objects)} mesh objects in '{collection_name}' collection")

    context = bpy.context
    manifest_entries = []

    for obj in objects:
        name = obj.name
        gltf_filename = f"{name}.glb"
        gltf_path = output_dir / gltf_filename

        print(f"  Exporting: {name} → {gltf_filename}")

        # Read material params before modifier application (modifiers don't affect materials)
        material = obj.data.materials[0] if obj.data.materials else None
        base_color, metallic, roughness = get_principled_bsdf_params(material)

        try:
            export_object_as_gltf(obj, gltf_path, context)
            success = True
        except Exception as e:
            print(f"    WARNING: Export failed for {name}: {e}", file=sys.stderr)
            success = False

        if success:
            manifest_entries.append({
                "name":       name,
                "gltf_file":  gltf_filename,
                "base_color": base_color,
                "metallic":   metallic,
                "roughness":  roughness,
                "actor_tags": [name],   # one tag per object — matches DA_DetectorVisibility
            })

    # Lights + cameras (numeric transforms in Blender world space; see module docstring)
    lights  = [] if args.no_lights  else export_lights()
    cameras = [] if args.no_cameras else export_cameras()

    # Write manifest.json
    manifest = {
        "sub_detectors": manifest_entries,
        "lights":        lights,
        "cameras":       cameras,
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nExported {len(manifest_entries)} sub-detectors, "
          f"{len(lights)} light(s), {len(cameras)} camera(s) to {output_dir}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
