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
      "gltf_file": "ECalBarrel.gltf",
      "base_color": [r, g, b, a],
      "metallic": 0.10,
      "roughness": 0.35,
      "actor_tags": ["ECalBarrel"]
    },
    ...
  ]
}

Notes:
- Iterates the "Detector" Blender collection (created by gdml_to_blender.py).
- Applies all modifiers (bevel, etc.) before export.
- Phi cutaway is already baked into mesh geometry — no extra handling needed.
- GLTF export: Y-forward convention corrected to UE5 Z-up via export_yup=True.
- Material params read from Principled BSDF node on each object's first material slot.
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
        gltf_filename = f"{name}.gltf"
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

    # Write manifest.json
    manifest = {"sub_detectors": manifest_entries}
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nExported {len(manifest_entries)} sub-detectors to {output_dir}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
