"""
inspect_blend.py — dump every rendering-relevant setting from a .blend.

Run via Blender headless:

    blender --background reference.blend --python scripts/inspect_blend.py \\
        -- > inspect.txt

The output covers: render engine + samples, color management, world shader
+ volume, all lights (type / energy / color / size / location), all
materials' Principled BSDF settings, compositor node tree, all cameras
(lens, DOF), and any particle systems / modifiers worth replicating.
"""
import sys
import bpy


def _truncate(s, n=80):
    s = str(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def section(name):
    print()
    print("=" * 72)
    print(name)
    print("=" * 72)


def dump_render():
    section("RENDER + COLOR MANAGEMENT")
    s = bpy.context.scene
    r = s.render
    print(f"engine: {r.engine}")
    print(f"resolution: {r.resolution_x}x{r.resolution_y}  @{r.resolution_percentage}%")
    print(f"motion_blur: {r.use_motion_blur}  shutter={r.motion_blur_shutter}")
    print(f"film_transparent: {r.film_transparent}")
    if hasattr(s, "cycles"):
        c = s.cycles
        for attr in ("device", "samples", "preview_samples",
                     "use_adaptive_sampling", "adaptive_threshold",
                     "adaptive_min_samples",
                     "use_denoising", "denoiser",
                     "max_bounces", "diffuse_bounces", "glossy_bounces",
                     "transmission_bounces", "volume_bounces",
                     "volume_step_rate", "volume_max_steps",
                     "use_light_tree",
                     "caustics_reflective", "caustics_refractive",
                     "film_exposure"):
            if hasattr(c, attr):
                print(f"cycles.{attr}: {getattr(c, attr)}")
    vs = s.view_settings
    print(f"view_transform: {vs.view_transform}")
    print(f"look: {vs.look}")
    print(f"exposure: {vs.exposure}")
    print(f"gamma: {vs.gamma}")


def _socket_default(socket):
    if socket.is_linked:
        return f"(linked: {socket.links[0].from_node.bl_idname}.{socket.links[0].from_socket.name})"
    try:
        v = socket.default_value
        if hasattr(v, "__iter__"):
            return "(" + ", ".join(f"{x:.4f}" for x in v) + ")"
        return f"{v:.4f}" if isinstance(v, float) else str(v)
    except Exception:
        return "<no default>"


def dump_nodes(tree, indent="    "):
    if tree is None:
        print(f"{indent}<no node tree>")
        return
    for node in tree.nodes:
        print(f"{indent}node: {node.bl_idname}  name={node.name!r}")
        # node-level properties worth grabbing for common node types
        for attr in ("blend_type", "operation", "interpolation", "color_ramp",
                     "glare_type", "size", "threshold", "quality", "mix",
                     "streaks", "iterations", "fade", "angle_offset",
                     "filter_type", "distortion", "dispersion",
                     "correction_method", "lift", "gamma", "gain",
                     "x", "y", "width", "height",
                     "direction_type", "axis"):
            if hasattr(node, attr):
                try:
                    val = getattr(node, attr)
                    if attr == "color_ramp":
                        elts = [(e.position, tuple(e.color)) for e in val.elements]
                        print(f"{indent}    {attr}: {elts}")
                    else:
                        print(f"{indent}    {attr}: {val}")
                except Exception:
                    pass
        for socket in node.inputs:
            print(f"{indent}    in.{socket.name}: {_socket_default(socket)}")


def dump_world():
    section("WORLD")
    w = bpy.context.scene.world
    if w is None:
        print("<no world>")
        return
    print(f"world: {w.name!r}")
    if hasattr(w, "mist_settings"):
        ms = w.mist_settings
        print(f"mist: start={ms.start} depth={ms.depth} falloff={ms.falloff}")
    if w.node_tree is None:
        print("<no node tree>")
        return
    dump_nodes(w.node_tree)


def dump_lights():
    section("LIGHTS")
    for obj in bpy.data.objects:
        if obj.type != "LIGHT":
            continue
        d = obj.data
        print(f"light: {obj.name!r}  type={d.type}")
        for attr in ("energy", "color", "shadow_soft_size", "use_shadow",
                     "size", "size_y", "spot_size", "spot_blend"):
            if hasattr(d, attr):
                v = getattr(d, attr)
                if hasattr(v, "__iter__") and not isinstance(v, str):
                    v = tuple(v)
                print(f"    {attr}: {v}")
        print(f"    location: {tuple(obj.location)}")
        print(f"    rotation: {tuple(obj.rotation_euler)}")
        if hasattr(d, "node_tree") and d.use_nodes:
            print("    light node tree:")
            dump_nodes(d.node_tree, indent="        ")


def dump_materials():
    section("MATERIALS")
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        print(f"material: {mat.name!r}")
        for sock_name in ("Base Color", "Metallic", "Roughness", "Specular IOR Level",
                          "Specular", "Anisotropic", "Anisotropy",
                          "Sheen Weight", "Sheen Tint", "Sheen Roughness",
                          "Coat Weight", "Coat Roughness", "Coat IOR",
                          "Coat Tint", "IOR", "Transmission Weight",
                          "Emission Color", "Emission Strength"):
            if sock_name in bsdf.inputs:
                print(f"    {sock_name}: {_socket_default(bsdf.inputs[sock_name])}")
        # full node tree (so we see noise/bump/coordinate setup)
        print("    node tree:")
        dump_nodes(mat.node_tree, indent="        ")


def dump_compositor():
    section("COMPOSITOR")
    s = bpy.context.scene
    if not getattr(s.render, "use_compositing", False):
        print("compositor: OFF")
    # 5.0 path
    if hasattr(s, "compositing_node_group"):
        ng = s.compositing_node_group
        if ng is not None:
            print("compositor node group (Blender 5.0+):")
            dump_nodes(ng)
            return
    # 4.x path
    if getattr(s, "use_nodes", False) and s.node_tree is not None:
        print("compositor node tree (Blender 4.x):")
        dump_nodes(s.node_tree)


def dump_cameras():
    section("CAMERAS")
    for obj in bpy.data.objects:
        if obj.type != "CAMERA":
            continue
        d = obj.data
        print(f"camera: {obj.name!r}  type={d.type}")
        print(f"    lens: {d.lens}mm")
        print(f"    clip: [{d.clip_start}, {d.clip_end}]")
        if d.type == "ORTHO":
            print(f"    ortho_scale: {d.ortho_scale}")
        if hasattr(d, "dof"):
            dof = d.dof
            print(f"    dof: use={dof.use_dof}  fstop={dof.aperture_fstop}  "
                  f"focus={dof.focus_distance}  blades={dof.aperture_blades}")
        print(f"    location: {tuple(obj.location)}")
        ad = obj.animation_data
        if ad is not None and ad.action is not None:
            print(f"    animation: action={ad.action.name}")


def dump_particles():
    section("PARTICLE SYSTEMS / VOLUMES / MODIFIERS")
    for obj in bpy.data.objects:
        psys_count = len(obj.particle_systems) if hasattr(obj, "particle_systems") else 0
        mods = [m for m in obj.modifiers] if hasattr(obj, "modifiers") else []
        if psys_count == 0 and not mods:
            continue
        print(f"object: {obj.name!r}  type={obj.type}")
        for p in obj.particle_systems:
            ps = p.settings
            print(f"    particles: name={p.name}  type={ps.type}  count={ps.count}")
            for attr in ("frame_start", "frame_end", "lifetime",
                         "emit_from", "physics_type", "size_random",
                         "particle_size"):
                if hasattr(ps, attr):
                    print(f"        {attr}: {getattr(ps, attr)}")
        for m in mods:
            print(f"    modifier: {m.type}  name={m.name!r}")


def main():
    dump_render()
    dump_world()
    dump_lights()
    dump_cameras()
    dump_compositor()
    dump_materials()
    dump_particles()


if __name__ == "__main__":
    main()
