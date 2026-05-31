#!/usr/bin/env python3
"""
bake_lightmaps.py — bake Cycles lighting into per-sub-detector textures and
export one self-contained GLB for the web viewer.

Run headlessly inside the ddgeoviztools image (Blender + trimesh), against a
scene built by `blender-scene` (materials + 5-light rig + phi cutaway):

    blender --background scene.blend --python-exit-code 1 \
        --python scripts/bake_lightmaps.py -- \
        --output-dir build/baked --resolution 1024 --samples 256

Pipeline per sub-detector (objects of the "Detector" collection):
  1. apply modifiers (weld / bevel / phi-cutaway) so baked geometry is final
  2. Smart-UV unwrap into a dedicated 'BakeUV' (the active-render UV -> glTF UV0)
  3. Cycles COMBINED bake (diffuse+glossy+emit, direct+indirect) into an image
  4. save the image and rebuild the material as an Emission of that image

Finally every baked object is exported to <output-dir>/detector_baked.glb plus
a manifest.json. The web app shows the GLB *unlit* — i.e. as the Blender render
— while AgX tone mapping is applied in three.js. The bake stores raw (scene
linear) light; it is NOT view-transformed here, so three.js does the grading.
"""

import argparse
import json
import math
import os
import sys

import bpy


def parse_args():
    argv = sys.argv
    rest = argv[argv.index("--") + 1 :] if "--" in argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--collection", default="Detector")
    p.add_argument("--resolution", type=int, default=1024)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--margin", type=int, default=6)
    p.add_argument("--uv-angle-limit", type=float, default=66.0, help="Smart-UV angle limit (deg)")
    p.add_argument("--uv-island-margin", type=float, default=0.02)
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


def setup_cycles(scene, samples, margin):
    scene.render.engine = "CYCLES"
    try:
        scene.cycles.device = "CPU"  # CI has no GPU
    except Exception as e:  # noqa: BLE001
        log(f"cycles.device: {e}")
    scene.cycles.samples = samples
    # Denoise off: the CI image may ship without OIDN shared libs (see
    # blender-render.yml DDGEOVIZTOOLS_DENOISE=0).
    for obj in (scene.cycles, getattr(scene, "cycles_curves", None)):
        if obj is not None and hasattr(obj, "use_denoising"):
            try:
                obj.use_denoising = False
            except Exception:  # noqa: BLE001
                pass

    bake = scene.render.bake
    bake.use_selected_to_active = False
    bake.margin = margin
    bake.use_clear = True
    for attr, val in [
        ("use_pass_direct", True),
        ("use_pass_indirect", True),
        ("use_pass_diffuse", True),
        ("use_pass_glossy", True),
        ("use_pass_transmission", False),
        ("use_pass_emit", True),
    ]:
        if hasattr(bake, attr):
            setattr(bake, attr, val)


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


def apply_modifiers(obj):
    select_only(obj)
    if obj.modifiers:
        try:
            bpy.ops.object.convert(target="MESH")  # applies enabled modifiers, keeps UVs/materials
        except RuntimeError as e:
            log(f"  convert (apply modifiers) failed on {obj.name}: {e}")


def smart_unwrap(obj, angle_limit_deg, island_margin):
    mesh = obj.data
    uv = mesh.uv_layers.get("BakeUV") or mesh.uv_layers.new(name="BakeUV")
    mesh.uv_layers.active = uv
    # Export this UV as glTF TEXCOORD_0.
    for layer in mesh.uv_layers:
        layer.active_render = layer.name == "BakeUV"
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=math.radians(angle_limit_deg),
        island_margin=island_margin,
    )
    bpy.ops.object.mode_set(mode="OBJECT")


def add_bake_targets(obj, image):
    """Give every material an active image-texture node so the bake has a target."""
    if not obj.material_slots:
        mat = bpy.data.materials.new(name=f"{obj.name}_mat")
        mat.use_nodes = True
        obj.data.materials.append(mat)
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            mat = bpy.data.materials.new(name=f"{obj.name}_mat")
            slot.material = mat
        if not mat.use_nodes:
            mat.use_nodes = True
        nt = mat.node_tree
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.label = "BAKE_TARGET"
        node.select = True
        nt.nodes.active = node


def emission_material(name, image):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def export_glb(objects, path):
    object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        export_yup=True,
        export_apply=False,  # modifiers already applied
        export_normals=True,
        export_texcoords=True,
        export_animations=False,
        check_existing=False,
    )


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    scene = bpy.context.scene
    setup_cycles(scene, args.samples, args.margin)

    objects = get_objects(args.collection)
    if not objects:
        log("ERROR: no mesh objects found to bake")
        sys.exit(1)
    log(f"{len(objects)} sub-detector(s); {args.resolution}px @ {args.samples} samples")

    manifest = {"glb": "detector_baked.glb", "objects": []}
    baked = []
    for obj in objects:
        name = obj.name
        log(f"-- {name}")
        try:
            apply_modifiers(obj)
            smart_unwrap(obj, args.uv_angle_limit, args.uv_island_margin)

            bake_img = bpy.data.images.new(
                f"bake_{name}", width=args.resolution, height=args.resolution, alpha=False
            )
            bake_img.colorspace_settings.name = "sRGB"
            add_bake_targets(obj, bake_img)

            select_only(obj)
            bpy.ops.object.bake(type="COMBINED")

            png = os.path.join(args.output_dir, f"{name}.png")
            bake_img.filepath_raw = png
            bake_img.file_format = "PNG"
            bake_img.save()

            # Reload as a FILE image so the GLB embeds a concrete texture.
            disp = bpy.data.images.load(png, check_existing=False)
            disp.colorspace_settings.name = "sRGB"
            obj.data.materials.clear()
            obj.data.materials.append(emission_material(f"{name}_baked", disp))

            manifest["objects"].append({"name": name, "texture": f"{name}.png"})
            baked.append(obj)
        except Exception as e:  # noqa: BLE001
            log(f"  FAILED {name}: {e}")

    if not baked:
        log("ERROR: nothing baked successfully")
        sys.exit(1)

    glb = os.path.join(args.output_dir, "detector_baked.glb")
    export_glb(baked, glb)
    with open(os.path.join(args.output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"done: {glb} ({len(baked)}/{len(objects)} objects)")


if __name__ == "__main__":
    main()
