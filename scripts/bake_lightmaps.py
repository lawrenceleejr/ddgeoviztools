#!/usr/bin/env python3
"""
bake_lightmaps.py — bake Cycles **ambient occlusion** into per-vertex colours and
export one self-contained GLB for the web viewer.

Run headlessly inside the ddgeoviztools image (Blender + trimesh), against a
scene built by `blender-scene`:

    blender --background scene.blend --python-exit-code 1 \
        --python scripts/bake_lightmaps.py -- \
        --output-dir build/baked --samples 128 [--preview build/preview.png]

Why AO (not full lighting): the detector is metallic, and a full-lighting bake of
metal is view-dependent — it bakes to near-black and looks nothing like the render
(verified extensively). The stunning metal look therefore comes from real-time
HDRI reflections in three.js. What *does* bake cleanly and view-independently is
ambient occlusion — the soft, ray-traced contact shadows / crevice darkening. We
bake that to vertex colours (glTF COLOR_0), keep the scene's PBR materials, and the
web app multiplies the AO under live image-based lighting.
"""

import argparse
import json
import os
import sys

import bpy


def parse_args():
    argv = sys.argv
    rest = argv[argv.index("--") + 1 :] if "--" in argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--collection", default="Detector")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--draco-level", type=int, default=6)
    p.add_argument("--preview", default=None, help="optional: render the baked AO to this PNG")
    return p.parse_args(rest)


def log(msg):
    print(f"[bake] {msg}", flush=True)


def get_objects(collection_name):
    coll = bpy.data.collections.get(collection_name)
    if coll is not None:
        objs = [o for o in coll.all_objects if o.type == "MESH"]
        if objs:
            return objs
    skip = {"Cameras", "Lights", "Cutters"}
    return [
        o
        for o in bpy.data.objects
        if o.type == "MESH" and not any(c.name in skip for c in o.users_collection)
    ]


def setup_cycles(scene, samples):
    scene.render.engine = "CYCLES"
    try:
        scene.cycles.device = "CPU"  # CI has no GPU
    except Exception as e:  # noqa: BLE001
        log(f"cycles.device: {e}")
    scene.cycles.samples = samples
    if hasattr(scene.cycles, "use_denoising"):
        try:
            scene.cycles.use_denoising = False  # CI image may lack OIDN
        except Exception:  # noqa: BLE001
            pass
    scene.render.bake.target = "VERTEX_COLORS"


def object_mode():
    if bpy.context.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:  # noqa: BLE001
            pass


def select_only(obj):
    object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.hide_render = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def bake_ao(obj):
    """Bake AO into a CORNER FLOAT_COLOR attribute named 'Bake' (exported as COLOR_0).
    Keeps the object's existing PBR materials so the GLB carries the palette."""
    select_only(obj)
    if obj.modifiers:
        try:
            bpy.ops.object.convert(target="MESH")  # apply weld / phi-cut, keep materials
        except RuntimeError as e:
            log(f"  convert failed on {obj.name}: {e}")
    mesh = obj.data
    ca = mesh.color_attributes.get("Bake") or mesh.color_attributes.new(
        name="Bake", type="FLOAT_COLOR", domain="CORNER"
    )
    try:
        mesh.color_attributes.active_color = ca
    except Exception:  # noqa: BLE001
        mesh.attributes.active_color_index = list(mesh.color_attributes).index(ca)
    select_only(obj)
    bpy.ops.object.bake(type="AO")
    return ca.name


def vertex_ao_preview_material(name, attr_name):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    try:
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = attr_name
    except Exception:  # noqa: BLE001
        vc = nt.nodes.new("ShaderNodeColorAttribute")
        vc.layer_name = attr_name
    nt.links.new(vc.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def export_glb(objects, path, draco_level):
    object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    kw = dict(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        # Scene physics-up is Blender +Y already -> pass axes through unchanged.
        export_yup=False,
        export_apply=False,
        export_normals=True,
        export_animations=False,
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=draco_level,
        check_existing=False,
    )
    props = bpy.ops.export_scene.gltf.get_rna_type().properties
    if "export_vertex_color" in props:
        kw["export_vertex_color"] = "ACTIVE"
    bpy.ops.export_scene.gltf(**kw)


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    scene = bpy.context.scene
    setup_cycles(scene, args.samples)

    objects = get_objects(args.collection)
    if not objects:
        log("ERROR: no mesh objects found to bake")
        sys.exit(1)
    log(f"{len(objects)} sub-detector(s) @ {args.samples} samples (AO vertex bake)")

    manifest = {"glb": "detector_baked.glb", "mode": "ao_vertex_colors", "objects": []}
    baked = []
    for obj in objects:
        log(f"-- {obj.name}")
        try:
            attr = bake_ao(obj)
            if args.preview:
                obj.data.materials.clear()
                obj.data.materials.append(vertex_ao_preview_material(f"{obj.name}_ao", attr))
            manifest["objects"].append({"name": obj.name})
            baked.append(obj)
        except Exception as e:  # noqa: BLE001
            log(f"  FAILED {obj.name}: {e}")

    if not baked:
        log("ERROR: nothing baked")
        sys.exit(1)

    glb = os.path.join(args.output_dir, "detector_baked.glb")
    export_glb(baked, glb, args.draco_level)
    with open(os.path.join(args.output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"exported {glb} ({len(baked)}/{len(objects)} objects)")

    if args.preview:
        cam = bpy.data.objects.get("Cam_Transverse") or scene.camera
        if cam:
            scene.camera = cam
        scene.view_settings.view_transform = "Standard"
        scene.render.resolution_x, scene.render.resolution_y = 1280, 960
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = args.preview
        bpy.ops.render.render(write_still=True)
        log(f"preview -> {args.preview}")


if __name__ == "__main__":
    main()
