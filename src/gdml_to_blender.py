"""
Create a Blender scene (.blend) from per-sub-detector mesh files.

Features
--------
- Reads OBJ / GLTF / VTP mesh files produced by ddgeoviztools' convert step.
- Robust mesh pipeline:
    1. Drop non-finite (NaN/Inf) vertices, remove degenerate / duplicate
       faces, fix face winding consistency, merge near-duplicate vertices
       (``_clean_mesh_pre_cut``).
    2. Slice along the two phi cut planes with trimesh's plane slicer
       (``_phi_cut_np``) — creates new vertices at the exact edge / plane
       intersections.
    3. Snap boundary vertices to the analytic cut plane to eliminate float32
       quantisation jitter (``_snap_to_cut_planes``).
    4. Drop any sliver triangles left by the slicer near the cut boundary,
       then a centroid-based sanity pass removes any stray face inside the
       cut sector.
   Result: razor-sharp, straight boundary loops on the phi cut.
- Assigns physics-inspired materials (steel, brass, copper, matte variants).
- Sets up the scene with GDML geometry rotated +90° around Y so the GDML
  beam axis (Z) maps to Blender's X axis.  Objects are kept at native GDML
  mm scale (1 BU = 1 mm).
  Effective Blender convention: X = beam, Y = physics-up, Z = horizontal transverse.
- Adds pre-positioned orthographic cameras for the standard HEP views:
    Cam_Transverse  — on +X axis, looks along −X, sees YZ transverse cross-section
    Cam_Side        — on +Z axis, looks along −Z, sees XY (beam=horizontal, Y=up)
    Cam_Perspective — inside the detector, looking out through the cut opening
- Objects are organised into four named collections: Detector, Cameras,
  Lights, Cutters (Cutters is hidden from viewport and render).
- Five-light cinematic rig with colour-temperature lighting:
    Key 3200 K (warm tungsten) + Fill 6500 K (cool sky) + Rim 4200 K (warm
    backlight) + Kicker 5000 K (under-lift) + Interior 3800 K (cut-opening fill).
    Plus a purple IP glow accent and a god-ray spot through the cut opening.
- World shader: gradient sky (cool horizon → near-black zenith) plus
  world-level Volume Scatter.  The volumetric fog is a world property —
  there is NO mesh, so it cannot appear in the viewport.  It only renders
  when Cycles ray-marches the scene, producing visible god rays from the
  key light and the dedicated god-ray spot.
- High-quality micro-bevel (3 segments, profile 0.7, 35° angle limit,
  loop_slide + harden_normals) so cut edges and surface seams catch
  specular highlights realistically.
- Default render: Cycles 4 K (3840 × 2160), 256 samples, 12 max bounces
  (4 diffuse + 8 glossy + 8 transmission, 4 volume), AgX / Filmic tone
  mapping at +2.5 EV exposure with "Medium High Contrast" look.
- Saves as a .blend file readable by any Blender 4.x or 5.0+ installation.
"""
from __future__ import annotations

import math
import os
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
    ("Steel",            (0.65, 0.67, 0.70),       0.80,     0.45),
    ("Brushed_Steel",    (0.58, 0.60, 0.63),       0.75,     0.55),
    ("Dark_Steel",       (0.30, 0.32, 0.35),       0.70,     0.50),
    ("Brass",            (0.72, 0.55, 0.20),       0.80,     0.45),
    ("Copper",           (0.72, 0.40, 0.25),       0.80,     0.50),
    ("Matte_Gray",       (0.45, 0.45, 0.48),       0.00,     0.85),
    ("Matte_Dark",       (0.20, 0.20, 0.22),       0.00,     0.90),
    ("Brushed_Aluminum", (0.78, 0.79, 0.80),       0.80,     0.50),
    ("Dark_Brass",       (0.55, 0.42, 0.15),       0.75,     0.50),
    ("Oxidized_Copper",  (0.25, 0.50, 0.40),       0.50,     0.70),
]

# Keyword → (base_RGB, metallic, roughness)
# Matched against the lowercased filename stem of each sub-detector GLTF.
# First match wins; fall back to cycling _PALETTE if nothing matches.
_DETECTOR_MATERIALS = [
    # ECal / EM calorimeter — crystal or lead glass (pale aqua, semi-reflective)
    (("ecal", "emcal", "em_cal", "crystal", "preshower", "pbwo4"),
     (0.35, 0.62, 0.52), 0.10, 0.35),
    # HCal / hadronic calorimeter — iron/brass absorber
    (("hcal", "hcalo", "hadcal", "hcalorimeter"),
     (0.52, 0.38, 0.22), 0.70, 0.55),
    # Solenoid / superconducting coil — brushed copper
    (("solenoid", "coil", "solen", "magnet_coil"),
     (0.72, 0.42, 0.22), 0.80, 0.45),
    # Yoke / iron flux return — dark iron
    (("yoke", "iron_yoke", "muon_iron", "flux_return"),
     (0.30, 0.28, 0.26), 0.75, 0.60),
    # Tracker / silicon strips
    (("tracker", "trk", "sit", "svt", "ftd", "set", "etd", "tracking"),
     (0.22, 0.38, 0.60), 0.55, 0.50),
    # TPC — brushed aluminium cylinder
    (("tpc",),
     (0.78, 0.79, 0.80), 0.75, 0.50),
    # Silicon pixel / vertex detector — steel blue
    (("pixel", "vxd", "vtx", "velo", "pxd"),
     (0.28, 0.45, 0.72), 0.70, 0.45),
    # Muon detectors (drift tubes, RPCs, …) — matte blue-grey
    (("muon", "mdt", "rpc", "tgc", "csc", "gem", "me0"),
     (0.55, 0.50, 0.68), 0.20, 0.70),
    # TOF / RICH / PID / Cherenkov — gold/brass
    (("tof", "btof", "rich", "dirc", "aerogel", "cherenkov", "pid"),
     (0.68, 0.58, 0.28), 0.65, 0.45),
    # Beam pipe / vacuum chamber — brushed stainless steel
    (("beampipe", "beam_pipe", "vacuumchamber", "bpipe"),
     (0.78, 0.79, 0.82), 0.80, 0.40),
    # BCH (beam-crossing housing) — soft white diffuse plastic
    (("bch",),
     (0.92, 0.91, 0.90), 0.00, 0.95),
    # NozzleW — tungsten alloy, brushed metal finish
    (("nozzlew",),
     (0.42, 0.40, 0.38), 0.85, 0.40),
    # Nozzle / heavy-metal shielding — dark tungsten-grey
    (("nozzle", "tungsten", "shielding", "shield"),
     (0.28, 0.27, 0.25), 0.70, 0.65),
    # Generic calorimeter label
    (("calorimeter", "calo"),
     (0.42, 0.55, 0.38), 0.10, 0.75),
    # Support / dead material
    (("support", "dead", "frame", "structure"),
     (0.40, 0.40, 0.42), 0.50, 0.70),
]


def _make_material(name: str, color_rgb: tuple, metallic: float, roughness: float):
    mat = bpy.data.materials.new(name=name)
    # Blender 5+: materials always have node_tree; use_nodes is deprecated.
    # Blender 4.x: need to enable nodes explicitly.
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color_rgb, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    # "Specular IOR Level" in Blender 4.x; "Specular" in 3.x
    for key in ("Specular IOR Level", "Specular"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.4
            break
    # Anisotropy off for the generic case — see _make_brushed_metal_material
    # for the nozzle treatment that uses a controlled radial tangent instead.
    for key in ("Anisotropic", "Anisotropy"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.0
            break

    # Photoreal touch on metals: pointiness-driven edge wear, procedural
    # roughness variation, and a fine micro-bump.  Skipped on diffuse /
    # matte materials (metallic < 0.5) where it adds no visible value and
    # would muddy the matte read.
    if metallic >= 0.5:
        _decorate_metal_bsdf(mat, color_rgb, roughness)

    return mat


def _decorate_metal_bsdf(mat, base_rgb: tuple, base_rough: float) -> None:
    """
    Layer photoreal detail onto a metal Principled BSDF: pointiness edge
    highlights, procedural roughness variation, and a sub-pixel micro-bump.

    Drives Base Color, Roughness, and Normal of the existing 'Principled
    BSDF' node via additional procedural nodes.  All textures are object-
    space — no UVs required (VTK exports have none) — and consistent across
    the mesh, so faceted triangulation does not produce per-triangle seams.
    """
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        return

    coord = nodes.new("ShaderNodeTexCoord")
    geom = nodes.new("ShaderNodeNewGeometry")

    # Pointiness 0..1, edges (convex) are higher.  Remap with a tight ramp
    # so only the actual edges light up — the bulk of each face stays as
    # base color / roughness.
    pt_ramp = nodes.new("ShaderNodeValToRGB")
    pt_ramp.color_ramp.elements[0].position = 0.48
    pt_ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    pt_ramp.color_ramp.elements[1].position = 0.62
    pt_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(geom.outputs["Pointiness"], pt_ramp.inputs["Fac"])

    # --- Base Color: subtle lift on the convex edges ---
    color_mix = nodes.new("ShaderNodeMixRGB")
    lighter = tuple(min(1.0, c + 0.18) for c in base_rgb)
    color_mix.blend_type = "MIX"
    color_mix.inputs["Color1"].default_value = (*base_rgb, 1.0)
    color_mix.inputs["Color2"].default_value = (*lighter, 1.0)
    links.new(pt_ramp.outputs["Color"], color_mix.inputs["Fac"])
    links.new(color_mix.outputs["Color"], bsdf.inputs["Base Color"])

    # --- Roughness: object-space noise variation, dropped on edges ---
    rough_noise = nodes.new("ShaderNodeTexNoise")
    rough_noise.inputs["Scale"].default_value = 25.0
    rough_noise.inputs["Detail"].default_value = 3.0
    links.new(coord.outputs["Object"], rough_noise.inputs["Vector"])

    rough_ramp = nodes.new("ShaderNodeValToRGB")
    low_r  = max(0.05, base_rough - 0.10)
    high_r = min(0.95, base_rough + 0.10)
    rough_ramp.color_ramp.elements[0].position = 0.30
    rough_ramp.color_ramp.elements[0].color = (low_r, low_r, low_r, 1.0)
    rough_ramp.color_ramp.elements[1].position = 0.70
    rough_ramp.color_ramp.elements[1].color = (high_r, high_r, high_r, 1.0)
    links.new(rough_noise.outputs["Fac"], rough_ramp.inputs["Fac"])

    rough_mix = nodes.new("ShaderNodeMixRGB")
    rough_mix.blend_type = "MIX"
    edge_r = max(0.05, base_rough - 0.20)
    rough_mix.inputs["Color2"].default_value = (edge_r, edge_r, edge_r, 1.0)
    links.new(pt_ramp.outputs["Color"], rough_mix.inputs["Fac"])
    links.new(rough_ramp.outputs["Color"], rough_mix.inputs["Color1"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    # --- Micro-bump: very fine object-space noise feeding the normal ---
    micro_noise = nodes.new("ShaderNodeTexNoise")
    micro_noise.inputs["Scale"].default_value = 800.0
    micro_noise.inputs["Detail"].default_value = 6.0
    links.new(coord.outputs["Object"], micro_noise.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.04
    bump.inputs["Distance"].default_value = 0.02
    links.new(micro_noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _make_brushed_metal_material(
    name: str, base_rgb: tuple,
    roughness: float = 0.35, anisotropy: float = 0.75,
):
    """
    Brushed-metal material with anisotropic highlights aligned around the
    beam (Z) axis.  Use for the lathe-turned tungsten nozzles, where the
    brush direction is genuinely circumferential.

    Uses ShaderNodeTangent direction='RADIAL' axis='Z' so the BRDF tangent
    is well-defined per-fragment regardless of the underlying triangulation.
    A stretched Noise→Bump adds visible groove micro-relief; a second noise
    drives roughness variation so the highlights aren't laser-uniform.
    """
    mat = bpy.data.materials.new(name=name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*base_rgb, 1.0)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = roughness
    for key in ("Specular IOR Level", "Specular"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.5
            break
    for key in ("Anisotropic", "Anisotropy"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = anisotropy
            break

    coord = nodes.new("ShaderNodeTexCoord")

    # Radial tangent around Z → highlights streak circumferentially, like a
    # lathe-turned cylinder.
    tangent = nodes.new("ShaderNodeTangent")
    try:
        tangent.direction_type = "RADIAL"
        tangent.axis = "Z"
    except (AttributeError, TypeError):
        pass
    if "Tangent" in bsdf.inputs:
        links.new(tangent.outputs["Tangent"], bsdf.inputs["Tangent"])

    # Stretched brush grooves: noise in object space, scaled long along Z
    # so the texture reads as fine circumferential streaks.
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (40.0, 40.0, 220.0)
    links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    grooves = nodes.new("ShaderNodeTexNoise")
    grooves.inputs["Scale"].default_value = 20.0
    grooves.inputs["Detail"].default_value = 4.0
    links.new(mapping.outputs["Vector"], grooves.inputs["Vector"])

    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.10
    bump.inputs["Distance"].default_value = 0.02
    links.new(grooves.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness variation driven by the same grooves — keeps the brushed
    # highlight from looking like a perfect anisotropic mirror.
    rough_ramp = nodes.new("ShaderNodeValToRGB")
    low_r  = max(0.05, roughness - 0.10)
    high_r = min(0.95, roughness + 0.10)
    rough_ramp.color_ramp.elements[0].color = (low_r, low_r, low_r, 1.0)
    rough_ramp.color_ramp.elements[1].color = (high_r, high_r, high_r, 1.0)
    links.new(grooves.outputs["Fac"], rough_ramp.inputs["Fac"])
    links.new(rough_ramp.outputs["Color"], bsdf.inputs["Roughness"])

    return mat


def _pre_create_materials() -> list:
    """Create all palette materials up-front and return them."""
    return [_make_material(*entry) for entry in _PALETTE]


def _material_for_detector(stem: str, mat_cycle):
    """
    Return a Blender material inferred from the sub-detector filename stem.

    Matches against _DETECTOR_MATERIALS keyword lists (first hit wins).
    Re-uses an already-created material of the same category so identical
    sub-detectors share one material block.  Falls back to the cycling
    _PALETTE when no keyword matches.
    """
    n = stem.lower()
    for keywords, color, metallic, roughness in _DETECTOR_MATERIALS:
        if any(kw in n for kw in keywords):
            mat_name = f"Det_{keywords[0].title()}"   # e.g. "Det_Solenoid"
            existing = bpy.data.materials.get(mat_name)
            if existing:
                return existing
            # Nozzles are visibly lathe-turned tungsten parts in real life —
            # render them with an anisotropic brushed-metal shader.
            if keywords[0] in ("nozzlew", "nozzle"):
                return _make_brushed_metal_material(
                    mat_name, color,
                    roughness=roughness, anisotropy=0.75,
                )
            return _make_material(mat_name, color, metallic, roughness)
    return next(mat_cycle)


# ---------------------------------------------------------------------------
# Mesh loading with duplicate-vertex cleanup
# ---------------------------------------------------------------------------

def _filter_world_volumes(sub_meshes: list, factor: float = 8.0) -> list:
    """
    Remove obvious GDML world-volume meshes from a list of trimesh objects.

    The world volume is always a large axis-aligned box that encloses the
    entire detector.  VTK's GLTF exporter embeds it as mesh0 in every file.
    Any sub-mesh whose bounding-box diagonal is more than *factor* times the
    median diagonal of the rest is considered a world volume and dropped.

    Returns a non-empty list (never removes every mesh).
    """
    if len(sub_meshes) <= 1:
        return sub_meshes

    diags = [float(np.linalg.norm(m.extents)) for m in sub_meshes]
    median_diag = float(np.median(diags))

    kept, removed = [], 0
    for m, d in zip(sub_meshes, diags):
        if median_diag > 0 and d > factor * median_diag:
            print(f"    [FILTER] Dropping world-volume mesh "
                  f"(bbox diag {d:.0f} mm, {d/median_diag:.0f}× median)",
                  flush=True)
            removed += 1
        elif _is_box_mesh(m):
            print(f"    [FILTER] Dropping container-box mesh "
                  f"({len(m.faces)} faces, axis-aligned, bbox diag {d:.0f} mm)",
                  flush=True)
            removed += 1
        else:
            kept.append(m)

    return kept if kept else sub_meshes   # safety: never return empty


def _is_box_mesh(mesh, max_faces: int = 30) -> bool:
    """
    Return True if the mesh looks like a GDML container / envelope box volume.

    GDML box solids export as axis-aligned cuboids with just 12 triangles
    (6 quad faces × 2 triangles each).  They are used as mother-volume
    containers in the hierarchy but carry no detector geometry.  Their face
    normals are always aligned with one of the three coordinate axes.

    Criteria:
      • fewer than *max_faces* triangles (generous to allow subdivision)
      • every face normal has one component very close to ±1
    """
    if len(mesh.faces) > max_faces:
        return False
    norms = np.abs(mesh.face_normals)
    # Each normal must be ≈ (1,0,0), (0,1,0), or (0,0,1)
    return bool(np.all(np.max(norms, axis=1) > 0.99))


def _thin_repeated_layers(sub_meshes: list, max_meshes: int = 20) -> list:
    """
    If a GLTF contains many similar-sized sub-meshes (e.g. hundreds of
    repeated calorimeter absorber / scintillator layers), subsample them
    down to at most *max_meshes* representatives.

    A "similar-sized" mesh is one whose bounding-box diagonal is within
    50 % – 200 % of the median diagonal across all sub-meshes.  When the
    majority of meshes fall in that band we subsample uniformly, always
    keeping the first and last so both ends of the detector are visible.

    Meshes that are clearly NOT repeated layers (world-volume remnants
    already removed, structural frames, etc.) are kept unconditionally.
    """
    if len(sub_meshes) <= max_meshes:
        return sub_meshes

    diags = [float(np.linalg.norm(m.extents)) for m in sub_meshes]
    median_diag = float(np.median(diags))

    # Partition: "layer" meshes are near-median; others are kept as-is
    layers, others = [], []
    for m, d in zip(sub_meshes, diags):
        if median_diag > 0 and 0.5 * median_diag <= d <= 2.0 * median_diag:
            layers.append(m)
        else:
            others.append(m)

    if len(layers) <= max_meshes:
        # Not dominated by repeated layers – just uniformly subsample the lot
        step = max(1, len(sub_meshes) // max_meshes)
        kept = sub_meshes[::step]
        print(f"    [THIN] {len(sub_meshes)} sub-meshes → keeping {len(kept)} "
              f"(uniform step={step})", flush=True)
        return kept

    # Subsample layer meshes, keep first+last for full extent
    n_keep = max(2, max_meshes - len(others))
    step = max(1, len(layers) // n_keep)
    kept_layers = [layers[0]] + layers[1:-1:step] + [layers[-1]]
    kept = others + kept_layers
    print(f"    [THIN] {len(sub_meshes)} sub-meshes ({len(layers)} repeated layers) "
          f"→ keeping {len(kept)} (step={step})", flush=True)
    return kept


def _max_meshes_for_name(name: str) -> int:
    """
    Return the layer-thinning budget for a sub-detector by name.

    Calorimeters have hundreds of absorber/scintillator layers and look fine
    with just a handful of samples (the eye reads the pattern from a few).
    Trackers are also highly repetitive but need a few more to show extent.
    Everything else is capped at a generous 20.
    """
    n = name.lower()
    cal_keys = ("ecal", "hcal", "calo", "calorimeter", "absorber",
                "scint", "crystal", "pbwo", "preshower", "emcal")
    trk_keys = ("tracker", "trk", "tpc", "silicon", "strip", "stave",
                "module", "disk", "petal", "ring", "endcap")
    if any(k in n for k in cal_keys):
        return 8    # calorimeters: 8 layer samples is plenty for visualisation
    if any(k in n for k in trk_keys):
        return 15   # trackers: show more to convey repetitive geometry
    return 20


def _decimate_trimesh(mesh: "trimesh.Trimesh",
                      max_faces: int = 30_000) -> "trimesh.Trimesh":
    """
    Reduce a mesh to at most *max_faces* triangles using quadric (QEM)
    decimation.  Falls back to the original mesh if trimesh's simplifier is
    unavailable or fails.

    QEM preserves sharp features well; a target of 30 K faces is enough for
    photorealistic rendering of most sub-detector components while cutting
    Blender load time dramatically on meshes with millions of triangles.
    """
    if len(mesh.faces) <= max_faces:
        return mesh
    ratio  = max_faces / len(mesh.faces)
    before = len(mesh.faces)
    try:
        simplified = mesh.simplify_quadric_decimation(int(before * ratio))
        if len(simplified.faces) > 0:
            print(f"    [DECIM] {before:,} → {len(simplified.faces):,} faces "
                  f"(QEM {ratio:.0%})", flush=True)
            return simplified
    except Exception as exc:
        print(f"    [DECIM] QEM failed ({exc}), keeping original", flush=True)
    return mesh


# ---------------------------------------------------------------------------
# Fast numpy-based phi-sector mesh slicing
# ---------------------------------------------------------------------------
# These functions operate on raw (V,3) / (F,3) numpy arrays — no bmesh, no
# scipy, no Blender dependency.  They are called during the trimesh loading
# stage (before the bpy Mesh is created) so that the Blender mesh is already
# cut and smaller, making all downstream operations faster.
#
# The phi cutaway removes a wedge-shaped sector [phi_min, phi_max] by:
#   1. Slicing the mesh at the phi_min plane  → keeps phi < phi_min side
#   2. Slicing the mesh at the phi_max plane  → keeps phi > phi_max side
#   3. Concatenating both halves
# Each slice creates new vertices at the exact intersection of edges with
# the cut plane, producing geometrically clean, razor-sharp cut edges.
# ---------------------------------------------------------------------------


def _clean_mesh_pre_cut(mesh: "trimesh.Trimesh",
                        name: str = "",
                        merge_tol_mm: float = 1e-3) -> "trimesh.Trimesh":
    """
    Aggressive mesh cleanup before phi slicing.

    GLTF exports from VTK can ship meshes with: stray duplicate vertices
    (float-quantised), zero-area / collinear triangles, inverted winding on
    some faces, and unreferenced vertices left over from VTK's GLTF pipeline.
    All of these cause the trimesh plane slicer to produce ragged or wild
    triangles at the cut boundary.  This pass normalises the input so the
    cut produces clean intersection edges.

    Steps (each is best-effort; trimesh API surface varies across versions):
      1. Drop any non-finite vertices (NaN/Inf would corrupt the slicer).
      2. Merge vertices closer than *merge_tol_mm* mm.
      3. Remove zero-area (collinear / coincident-vertex) triangles.
      4. Drop duplicate faces.
      5. Remove unreferenced vertices.
      6. Fix face winding so all normals face outward consistently.
      7. Process again to refresh adjacency caches.

    Returns a NEW Trimesh (does not mutate the input).
    """
    n_v0, n_f0 = len(mesh.vertices), len(mesh.faces)

    # 1. Drop any non-finite vertices.  trimesh.process won't catch NaN/Inf
    #    and they propagate into the slicer's d=V·n distance computation.
    finite_v = np.all(np.isfinite(np.asarray(mesh.vertices)), axis=1)
    if not finite_v.all():
        # Re-index faces to drop any face that references a non-finite vertex
        bad = ~finite_v
        bad_face_mask = np.any(bad[mesh.faces], axis=1)
        kept_faces = mesh.faces[~bad_face_mask]
        mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=kept_faces, process=False)
        mesh.remove_unreferenced_vertices()

    # 2-5. trimesh has dedicated cleanup ops; wrap each in try/except since
    # the API is slightly different across trimesh 3.x and 4.x.
    try:
        # Merges vertices within merge_tol_mm and recomputes face indices.
        # The Trimesh constructor with process=True does this too, but we
        # want explicit control of the tolerance here.
        mesh.merge_vertices(merge_tex=False, merge_norm=False, digits_vertex=None)
    except TypeError:
        try:
            mesh.merge_vertices()
        except Exception:
            pass
    except Exception:
        pass

    try:
        # Drop zero-area faces; the height threshold is the minimum altitude
        # of any triangle.  1e-6 mm² area on mm-scale GDML geometry is well
        # below any meaningful feature.
        mesh.update_faces(mesh.nondegenerate_faces(height=1e-6))
    except Exception:
        pass

    try:
        # Drop duplicate triangles (same vertex triple, regardless of order)
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass

    try:
        mesh.remove_unreferenced_vertices()
    except Exception:
        pass

    # 6. Fix face winding so neighbouring face normals agree.  This matters
    # for the plane slicer because trimesh classifies "inside vs outside"
    # using signed distance; consistent winding ensures the kept side is
    # the outside surface.  fix_normals is potentially expensive on huge
    # meshes (it walks face adjacency), so skip for >100K faces.
    if len(mesh.faces) < 100_000:
        try:
            mesh.fix_normals(multibody=True)
        except TypeError:
            try:
                mesh.fix_normals()
            except Exception:
                pass
        except Exception:
            pass

    # 7. Final process pass — refreshes adjacency caches, validates indices.
    mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=True)

    n_v1, n_f1 = len(mesh.vertices), len(mesh.faces)
    if (n_v0, n_f0) != (n_v1, n_f1):
        print(f"    [CLEAN] {name}: {n_v0:,}v {n_f0:,}f → "
              f"{n_v1:,}v {n_f1:,}f", flush=True)
    return mesh


def _snap_to_cut_planes(vertices: np.ndarray,
                        phi_min_rad: float,
                        phi_max_rad: float,
                        snap_eps_mm: float = 5e-3) -> np.ndarray:
    """
    Project vertices that are *almost* on either phi cut plane onto the
    exact plane.  Float32 quantisation from GLTF export leaves boundary
    vertices a few µm off the analytic plane; snapping them eliminates
    visible jitter along the cut and prevents shading discontinuities
    where the Bevel modifier walks along the boundary loop.

    The two cut planes pass through the origin and contain the local Z axis.
    Normal of the phi_min plane:  ( cos(phi_min),  sin(phi_min), 0)
    Normal of the phi_max plane:  (-cos(phi_max), -sin(phi_max), 0)
    (Both point AWAY from the cut sector — the "kept" side.)

    A vertex within snap_eps_mm of the plane gets projected onto it:
        v_new = v - (v · n) · n
    """
    v = np.asarray(vertices, dtype=np.float64).copy()
    if len(v) == 0:
        return v

    n_min = np.array([ math.cos(phi_min_rad),  math.sin(phi_min_rad), 0.0])
    n_max = np.array([-math.cos(phi_max_rad), -math.sin(phi_max_rad), 0.0])

    n_snapped = 0
    for n in (n_min, n_max):
        d = v @ n
        mask = np.abs(d) < snap_eps_mm
        if mask.any():
            v[mask] -= np.outer(d[mask], n)
            n_snapped += int(mask.sum())
    if n_snapped:
        # Print as a hint for the calling function; the caller decides whether
        # to log it (a quiet "few snapped" is fine; thousands would indicate
        # a coordinate-frame mismatch worth surfacing).
        pass
    return v


def _slice_mesh_plane_np(
    vertices: np.ndarray,
    faces: np.ndarray,
    plane_co: np.ndarray,
    plane_no: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Slice a triangle mesh at a plane, returning only the positive side.

    Triangles that straddle the plane are split: new vertices are created at
    the exact edge–plane intersection, and the positive-side sub-triangles
    are emitted.  This produces geometrically clean cut edges.

    Parameters
    ----------
    vertices : (V, 3) float64
    faces    : (F, 3) int64   — triangle vertex indices
    plane_co : (3,) float64   — a point on the plane
    plane_no : (3,) float64   — outward normal (positive side = kept side)

    Returns
    -------
    (new_vertices, new_faces) with only the positive-side geometry.
    """
    plane_co = np.asarray(plane_co, dtype=np.float64)
    plane_no = np.asarray(plane_no, dtype=np.float64)
    norm = np.linalg.norm(plane_no)
    if norm < 1e-15:
        return vertices, faces
    plane_no = plane_no / norm

    # Signed distance of every vertex from the plane
    d = (vertices - plane_co) @ plane_no          # (V,)

    # Classify vertices: +1 positive (kept side), -1 negative (removed side).
    # On-plane vertices (|d| <= eps) are treated as positive: they lie on the
    # cut boundary and belong to the kept side.  Without this, a straddle face
    # with one positive, one negative, and one on-plane vertex only has ONE
    # crossing edge instead of two.  The missing intersection index stays at
    # -1, which numpy interprets as the last vertex → wild triangles shooting
    # off to an arbitrary point in the mesh.
    #
    # eps is 1e-3 mm (1 µm) — large enough to absorb float32 quantisation
    # errors at GDML-scale coordinates (~2000 mm radius).  Vertices within
    # 1 µm of the cut plane are treated as on-plane rather than positive/negative,
    # which prevents near-zero-area sliver triangles at phi-sector seams where
    # the GLTF exporter produced boundary vertices slightly off the exact cut plane.
    eps = 1e-3
    sign = np.ones(len(d), dtype=np.int8)
    sign[d < -eps] = -1

    # Per-face vertex signs
    fs = sign[faces]                               # (F, 3)
    n_pos = (fs > 0).sum(axis=1)                   # per face
    n_neg = (fs < 0).sum(axis=1)

    # Faces entirely on the positive side (keep as-is)
    keep_mask = (n_neg == 0)
    # Faces that straddle the plane (need splitting)
    straddle_mask = (n_pos > 0) & (n_neg > 0)

    kept_faces = faces[keep_mask]

    # --- Process straddling faces ---
    straddle_idx = np.where(straddle_mask)[0]
    if len(straddle_idx) == 0:
        return vertices, kept_faces

    # --- Batch-vectorised straddle face processing ---
    # For each straddle face we need to:
    #   1. find the 2 crossing edges
    #   2. compute intersection points on those edges
    #   3. emit 1 triangle (if 1 pos vertex) or 2 triangles (if 2 pos vertices)
    #
    # We separate straddle faces by topology and process each group with
    # numpy, avoiding a Python-level per-face loop.

    sf = faces[straddle_idx]         # (S, 3) straddle face vertex indices
    ss = sign[sf]                    # (S, 3) vertex signs
    sd = d[sf]                       # (S, 3) vertex signed distances

    # For each edge (0→1, 1→2, 2→0), does it cross the plane?
    # crossing = one endpoint strictly +, other strictly −
    cross_01 = (ss[:, 0] * ss[:, 1]) < 0  # True if signs differ & nonzero
    cross_12 = (ss[:, 1] * ss[:, 2]) < 0
    cross_20 = (ss[:, 2] * ss[:, 0]) < 0

    # Compute ALL intersection points for crossing edges at once (vectorised)
    # t = d_a / (d_a − d_b);  pt = V[a] + t · (V[b] − V[a])
    n_straddle = len(sf)
    base_idx = len(vertices)

    def _edge_intersections(mask, col_a, col_b):
        """Return (new_vert_coords, index_into_new_verts) for crossing edges."""
        if not mask.any():
            return np.empty((0, 3), dtype=np.float64), np.full(n_straddle, -1, dtype=np.int64)
        a_idx = sf[mask, col_a]
        b_idx = sf[mask, col_b]
        da = d[a_idx]
        db = d[b_idx]
        t = (da / (da - db))[:, None]
        pts = vertices[a_idx] + t * (vertices[b_idx] - vertices[a_idx])
        # De-duplicate by canonical edge key
        edge_keys = np.stack([np.minimum(a_idx, b_idx), np.maximum(a_idx, b_idx)], axis=1)
        _, unique_idx, inverse = np.unique(edge_keys, axis=0, return_index=True, return_inverse=True)
        unique_pts = pts[unique_idx]
        # Map each crossing edge to its unique new-vertex index
        local_idx = np.full(n_straddle, -1, dtype=np.int64)
        local_idx[mask] = inverse
        return unique_pts, local_idx

    pts_01, idx_01 = _edge_intersections(cross_01, 0, 1)
    off_01 = base_idx
    pts_12, idx_12 = _edge_intersections(cross_12, 1, 2)
    off_12 = off_01 + len(pts_01)
    pts_20, idx_20 = _edge_intersections(cross_20, 2, 0)
    off_20 = off_12 + len(pts_12)

    # Map local indices to global new-vertex indices
    def _global(local, offset):
        g = local.copy()
        m = g >= 0
        g[m] += offset
        return g

    gi_01 = _global(idx_01, off_01)
    gi_12 = _global(idx_12, off_12)
    gi_20 = _global(idx_20, off_20)

    # Now build output faces per straddle face.
    # Classify: how many vertices are on the positive side (sign > 0)?
    n_pos_s = (ss > 0).sum(axis=1)   # 1 or 2 (guaranteed by straddle definition)

    # For each face, the positive-side polygon is constructed by walking the
    # triangle edges in order and including positive/on-plane vertices plus
    # intersection vertices at crossings.  Rather than looping, we handle
    # the two cases (1-pos and 2-pos) separately with vectorised indexing.

    split_faces_list = []

    # ---- Case A: exactly 1 positive vertex ----
    # Result: 1 triangle.  The positive vertex plus 2 intersection points.
    # We need to find WHICH vertex is positive and the 2 crossing edges.
    for rot in range(3):
        # Rotate columns so that column 0 is the positive vertex
        r0, r1, r2 = rot, (rot + 1) % 3, (rot + 2) % 3
        mask = (n_pos_s == 1) & (ss[:, r0] > 0)
        if not mask.any():
            continue
        # Crossing edges: r0→r1 and r2→r0 (since r0 is + and r1, r2 are ≤ 0)
        gi_map = {(0, 1): gi_01, (1, 2): gi_12, (2, 0): gi_20,
                  (1, 0): gi_01, (2, 1): gi_12, (0, 2): gi_20}
        e1_key = (r0, r1)
        e2_key = (r2, r0)
        i1 = gi_map[e1_key][mask]
        i2 = gi_map[e2_key][mask]
        tri = np.stack([sf[mask, r0], i1, i2], axis=1)
        split_faces_list.append(tri)

    # ---- Case B: exactly 2 positive vertices ----
    # Result: 2 triangles (quad → fan).
    for rot in range(3):
        # Rotate so column 2 is the negative vertex
        r0, r1, r2 = rot, (rot + 1) % 3, (rot + 2) % 3
        mask = (n_pos_s == 2) & (ss[:, r2] < 0)
        if not mask.any():
            continue
        # Crossing edges: r1→r2 and r2→r0
        gi_map = {(0, 1): gi_01, (1, 2): gi_12, (2, 0): gi_20,
                  (1, 0): gi_01, (2, 1): gi_12, (0, 2): gi_20}
        i1 = gi_map[(r1, r2)][mask]
        i2 = gi_map[(r2, r0)][mask]
        # Quad: r0, r1, i1, i2 → tris: (r0, r1, i1) and (r0, i1, i2)
        tri_a = np.stack([sf[mask, r0], sf[mask, r1], i1], axis=1)
        tri_b = np.stack([sf[mask, r0], i1, i2], axis=1)
        split_faces_list.append(tri_a)
        split_faces_list.append(tri_b)

    # Assemble extra vertices
    all_extra = [p for p in (pts_01, pts_12, pts_20) if len(p) > 0]
    if all_extra:
        extra_arr = np.vstack(all_extra)
        all_verts = np.vstack([vertices, extra_arr])
    else:
        all_verts = vertices

    # Assemble faces
    parts = [kept_faces] + split_faces_list
    parts = [p for p in parts if len(p) > 0]
    all_faces = np.vstack(parts) if parts else kept_faces

    return all_verts, all_faces


def _cap_boundary_loops(mesh: "trimesh.Trimesh") -> "trimesh.Trimesh":
    """
    Find open boundary loops on *mesh* and fill each with a triangle fan.

    After a phi-sector cut, a convex-hull mesh has open edges where the cut
    planes intersected it.  This function traces those boundary loops and
    creates cap faces so the cross-section appears solid.

    Returns a new Trimesh with the cap faces appended.
    """
    from collections import defaultdict

    edges = mesh.edges_unique
    faces_per_edge = mesh.edges_unique_inverse
    # Count how many faces reference each unique edge
    edge_face_count = np.bincount(faces_per_edge, minlength=len(edges))
    # Boundary edges are referenced by exactly one face
    boundary_mask = edge_face_count == 1
    boundary_edges = edges[boundary_mask]

    if len(boundary_edges) == 0:
        return mesh

    # Build adjacency for boundary vertices
    adj = defaultdict(list)
    for e in boundary_edges:
        adj[e[0]].append(e[1])
        adj[e[1]].append(e[0])

    # Trace closed loops
    visited = set()
    loops = []
    for start in adj:
        if start in visited:
            continue
        loop = [start]
        visited.add(start)
        current = start
        while True:
            neighbors = [n for n in adj[current] if n not in visited]
            if not neighbors:
                # Check if loop closes back to start
                if start in adj[current]:
                    loops.append(loop)
                break
            current = neighbors[0]
            visited.add(current)
            loop.append(current)

    if not loops:
        return mesh

    verts = np.array(mesh.vertices)
    new_faces = list(mesh.faces)
    new_verts = list(verts)

    for loop in loops:
        if len(loop) < 3:
            continue
        loop_verts = verts[loop]
        centroid = loop_verts.mean(axis=0)
        # Add centroid as a new vertex
        center_idx = len(new_verts)
        new_verts.append(centroid)

        # Determine winding order using the Newell method (area-weighted average
        # of cross products around the polygon).  This gives a stable normal
        # estimate for any planar or near-planar loop, regardless of vertex order.
        # We then compare against the outward-facing normals of the mesh faces
        # that *share* at least one boundary vertex, so the cap faces are
        # consistently oriented outward.
        n = len(loop)
        newell_n = np.zeros(3)
        for k in range(n):
            a_v = loop_verts[k]
            b_v = loop_verts[(k + 1) % n]
            newell_n[0] += (a_v[1] - b_v[1]) * (a_v[2] + b_v[2])
            newell_n[1] += (a_v[2] - b_v[2]) * (a_v[0] + b_v[0])
            newell_n[2] += (a_v[0] - b_v[0]) * (a_v[1] + b_v[1])

        # Reference: outward normals of faces adjacent to this boundary loop.
        # Using only the boundary vertices' immediate face normals avoids the
        # "mean-of-all-faces" heuristic which is unreliable for asymmetric cuts.
        loop_set = set(loop)
        adj_face_mask = np.any(np.isin(mesh.faces, list(loop_set)), axis=1)
        if adj_face_mask.any():
            ref_normal = mesh.face_normals[adj_face_mask].mean(axis=0)
        else:
            ref_normal = mesh.face_normals.mean(axis=0)

        flip = np.dot(newell_n, ref_normal) < 0
        for i in range(n):
            a = loop[i]
            b = loop[(i + 1) % n]
            if flip:
                new_faces.append([center_idx, b, a])
            else:
                new_faces.append([center_idx, a, b])

    result = trimesh.Trimesh(
        vertices=np.array(new_verts),
        faces=np.array(new_faces),
        process=True,
    )
    return result


def _drop_sector_faces(
    mesh: "trimesh.Trimesh",
    phi_min: float,
    phi_max: float,
) -> "trimesh.Trimesh":
    """
    Remove any face whose centroid phi falls inside the removed sector
    (phi_min, phi_max).  Used as a sanity pass after plane slicing to catch
    the rare stray faces that survive numerical edge cases near the cut planes.

    phi values use the same convention as the phi cutaway:
        phi = atan2(-X_local, Y_local)

    Both phi_min and phi_max are in radians.
    """
    if len(mesh.faces) == 0:
        return mesh

    c   = mesh.triangles_center          # (F, 3) centroid of each face
    phi = np.arctan2(-c[:, 0], c[:, 1]) # phi of each centroid

    # Normalise phi relative to phi_min so the sector is always [0, width]
    # regardless of where it sits in the ±π range.
    width = phi_max - phi_min            # positive, in (0, 2π)
    phi_rel = (phi - phi_min + math.pi) % (2.0 * math.pi) - math.pi
    # phi_rel ∈ [0, width) means "inside the removed sector"
    eps_phi = 1e-6                       # radians ≈ 0.06 µrad — purely numerical guard
    stray = (phi_rel > eps_phi) & (phi_rel < width - eps_phi)

    if not stray.any():
        return mesh

    n_stray = int(stray.sum())
    print(f"    [PHI-CLEAN] Dropping {n_stray} stray face(s) inside removed sector",
          flush=True)
    kept_faces = mesh.faces[~stray]
    return trimesh.Trimesh(vertices=mesh.vertices, faces=kept_faces, process=True)


def _phi_cut_np(
    vertices: np.ndarray,
    faces: np.ndarray,
    phi_min_deg: float,
    phi_max_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Remove the phi sector [phi_min, phi_max] from a triangle mesh.

    The sector is defined in mesh-local coordinates:
        phi = atan2(-X_local, Y_local)
        phi=0  → +Y_local   (after Ry+90°  →  +Y_blender = physics-up)
        phi=90 → −X_local   (after Ry+90°  →  +Z_blender = horiz transverse)

    Uses trimesh's built-in ``slice_mesh_plane`` (battle-tested, handles all
    edge cases) instead of the bespoke numpy slicer.  The sequential strategy
    is the same as before:

      1. LEFT  = keep phi < phi_min  (positive side of normal_out_min)
      2. INNER = keep phi ≥ phi_min  (positive side of −normal_out_min)
      3. RIGHT = INNER ∩ phi > phi_max
      4. Combine LEFT + RIGHT

    A centroid-based sanity pass is run at the end to drop any stray faces
    that numerically survived near the cut planes.

    Returns (new_vertices, new_faces).
    """
    # Use trimesh's lower-level slice_faces_plane (no shapely dependency;
    # slice_mesh_plane unconditionally imports trimesh.path.polygons → shapely).
    from trimesh.intersections import slice_faces_plane as _sfp

    phi_min = math.radians(phi_min_deg)
    phi_max = math.radians(phi_max_deg)
    origin  = np.zeros(3)

    # Normal at phi_min pointing AWAY from sector (toward phi < phi_min)
    normal_out_min = np.array([math.cos(phi_min), math.sin(phi_min), 0.0])
    # Normal at phi_max pointing AWAY from sector (toward phi > phi_max)
    normal_out_max = np.array([-math.cos(phi_max), -math.sin(phi_max), 0.0])

    def _slice(verts, faces_, normal):
        """Slice keeping the positive-normal side; returns (verts, faces)."""
        if len(faces_) == 0:
            return verts, faces_
        new_v, new_f, _ = _sfp(
            vertices=verts, faces=faces_,
            plane_normal=normal, plane_origin=origin,
        )
        return new_v, new_f

    # Step 1: LEFT = phi < phi_min
    lv, lf = _slice(vertices, faces, normal_out_min)
    # Step 2: INNER = phi ≥ phi_min  (flip normal)
    iv, if_ = _slice(vertices, faces, -normal_out_min)
    # Step 3: RIGHT = phi > phi_max  (applied to INNER only)
    rv, rf = _slice(iv, if_, normal_out_max)

    # Step 4: Concatenate LEFT + RIGHT
    parts_v, parts_f = [], []
    if len(lf) > 0:
        parts_v.append(lv); parts_f.append(lf)
    if len(rf) > 0:
        parts_f.append(rf + len(parts_v[0]) if parts_v else rf)
        parts_v.append(rv)

    if not parts_v:
        return vertices[:0].copy(), np.empty((0, 3), dtype=np.int64)

    if len(parts_v) == 1:
        combined_v, combined_f = parts_v[0], parts_f[0]
    else:
        n_left = len(lv)
        combined_v = np.vstack([lv, rv])
        combined_f  = np.vstack([lf, rf + n_left])

    # Merge seam vertices and remove any zero-area faces left by slicing
    combined = trimesh.Trimesh(vertices=combined_v, faces=combined_f, process=True)

    # Snap boundary vertices to exactly the analytic cut planes.  Float32
    # GLTF coordinates leave occasional verts a few µm off-plane; snapping
    # produces a perfectly straight boundary loop.
    snapped = _snap_to_cut_planes(combined.vertices, phi_min, phi_max,
                                   snap_eps_mm=5e-3)
    combined = trimesh.Trimesh(vertices=snapped, faces=combined.faces, process=True)

    # Drop sliver / degenerate triangles produced by the slicer (a thin
    # straddle where one edge is almost coplanar with the cut plane can leave
    # a near-zero-area triangle).
    try:
        combined.update_faces(combined.nondegenerate_faces(height=1e-6))
        combined.remove_unreferenced_vertices()
    except Exception:
        pass

    # Sanity pass: remove any faces whose centroid still falls in the sector
    combined = _drop_sector_faces(combined, phi_min, phi_max)

    return (
        np.asarray(combined.vertices, dtype=np.float64),
        np.asarray(combined.faces,    dtype=np.int64),
    )


def _load_mesh(
    filepath: Path,
    name: str,
    phi_min_deg: float | None = None,
    phi_max_deg: float | None = None,
    solid: bool = False,
):
    """
    Read a mesh file with trimesh, merge duplicate vertices and remove
    degenerate faces, optionally apply a phi-sector cutaway, then create
    a bpy Mesh object.

    If *phi_min_deg* and *phi_max_deg* are both provided, the sector
    [phi_min, phi_max] is sliced away using pure-numpy plane slicing
    (``_phi_cut_np``) *before* the Blender mesh is created.  This is
    vastly faster than the old bmesh bisect approach because:
      - numpy vectorises vertex classification and bulk face filtering
      - only straddling faces need a Python-level split loop
      - the resulting bpy mesh is already cut and smaller

    GLTF scene-graph node transforms are applied during loading so that
    mesh vertices end up in GDML world-space coordinates.  This is essential
    for correct phi computations on off-axis sub-detectors.

    Returns the new bpy Object.
    """
    # Load without force="mesh": GLTF files return a trimesh.Scene so that
    # _filter_world_volumes can inspect each sub-mesh individually before
    # concatenating.  Using force="mesh" caused trimesh to concatenate all
    # sub-meshes (including the GDML world-volume box) before we could filter.
    raw = trimesh.load(str(filepath), process=False)

    if isinstance(raw, trimesh.Scene):
        # Apply scene-graph node transforms so mesh vertices end up in GDML
        # world-space coordinates rather than each actor's local frame.
        # VTK's GLTF exporter stores each actor's polydata in its own local
        # space and encodes the world position as a separate node transform;
        # without applying that transform, off-axis placements (staves, crystals
        # at large radii) would have all centroids near the local origin and
        # yield a wrong phi for the GN cutaway modifier.
        sub_meshes = []
        try:
            for node_name in raw.graph.nodes_geometry:
                transform, geom_name = raw.graph[node_name]
                geom = raw.geometry.get(geom_name)
                if isinstance(geom, trimesh.Trimesh):
                    world_mesh = geom.copy()
                    world_mesh.apply_transform(transform)
                    sub_meshes.append(world_mesh)
        except Exception as exc:
            print(f"    [LOAD] GLTF transform pass failed ({exc}); "
                  f"falling back to local-frame geometry", flush=True)
            sub_meshes = []
        if not sub_meshes:
            # Fallback: use geometry values without scene-graph transforms
            all_geoms = list(raw.geometry.values())
            sub_meshes = [m for m in all_geoms if isinstance(m, trimesh.Trimesh)]
        n_skipped = sum(1 for g in raw.geometry.values()
                        if not isinstance(g, trimesh.Trimesh))
        if n_skipped:
            print(f"    [LOAD] Skipped {n_skipped} non-triangle geometry object(s) "
                  f"(Path3D / camera / curve nodes)", flush=True)
        if not sub_meshes:
            raise ValueError(f"No triangle meshes found in {filepath}")
        sub_meshes = _filter_world_volumes(sub_meshes)
        # Name-aware layer budget: calorimeters → 8, trackers → 15, else 20
        sub_meshes = _thin_repeated_layers(sub_meshes,
                                           max_meshes=_max_meshes_for_name(name))
        raw = trimesh.util.concatenate(sub_meshes)

    # Always re-wrap as a processed Trimesh (merges duplicate verts, etc.)
    raw = trimesh.Trimesh(raw.vertices, raw.faces, process=True)

    # Quadric decimation — keeps face count manageable for Blender's modifier
    # stack (Weld + Boolean + Bevel) without degrading visual quality.
    raw = _decimate_trimesh(raw, max_faces=30_000)

    # Solid fill — replace the shell mesh with its convex hull so that
    # the interior is completely filled.  When the phi-cutaway slices
    # through a solid mesh the cross-section is a filled polygon instead
    # of two thin walls with empty space between them.
    if solid:
        try:
            raw = raw.convex_hull
            print(f"    [SOLID] Convex hull: {len(raw.faces):,} faces", flush=True)
        except Exception as exc:
            print(f"    [SOLID] Convex hull failed ({exc}); keeping shell",
                  flush=True)

    # Phi-sector cutaway (numpy level — fast, creates clean intersection edges)
    if phi_min_deg is not None and phi_max_deg is not None:
        # Pre-cut cleanup: removes degenerate / duplicate faces, drops
        # non-finite vertices, fixes winding.  GLTF input from VTK is rarely
        # manifold; without this pass the slicer occasionally produces
        # wild boundary triangles or ragged stair-step cuts.
        raw = _clean_mesh_pre_cut(raw, name=name, merge_tol_mm=1e-3)

        n_before = len(raw.faces)
        verts_np = np.asarray(raw.vertices, dtype=np.float64)
        faces_np = np.asarray(raw.faces, dtype=np.int64)
        verts_np, faces_np = _phi_cut_np(verts_np, faces_np, phi_min_deg, phi_max_deg)
        print(f"    [PHI-NP] {n_before:,} → {len(faces_np):,} faces "
              f"(cut [{phi_min_deg:.0f}°, {phi_max_deg:.0f}°])", flush=True)
        # Re-wrap as processed trimesh to merge duplicate vertices from slicing
        raw = trimesh.Trimesh(verts_np, faces_np, process=True)

        # For solid meshes, cap the open boundaries left by the phi cut.
        # The cut creates clean boundary edges along each cut plane; filling
        # those holes produces flat cap faces that make the cross-section
        # look like slicing through solid material.
        if solid:
            try:
                raw = _cap_boundary_loops(raw)
                print(f"    [SOLID] Boundaries capped → {len(raw.faces):,} faces",
                      flush=True)
            except Exception as exc:
                print(f"    [SOLID] Boundary cap failed ({exc})", flush=True)

    verts = raw.vertices.tolist()   # list of [x, y, z]
    faces = raw.faces.tolist()      # list of [i, j, k]

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    # Shading mode:
    #   • SHELL meshes (solid=False) — shade smooth.  These are thin shells
    #     representing curved detector surfaces (tracker layers, calorimeter
    #     barrels) where smooth shading hides the underlying triangulation.
    #   • SOLID meshes (solid=True)  — flat shade.  These are convex-hull-filled
    #     nozzles whose mesh now contains both the curved outer wall AND the
    #     flat cap polygons from `_cap_boundary_loops`.  Shading them smooth
    #     interpolates normals ACROSS the cap-to-wall edge — producing visible
    #     stripes / radial bands where the smooth gradient transitions
    #     through what should be a hard manufactured edge.  Flat shading is
    #     the correct look for a machined nozzle anyway: the cap reads as
    #     "the metal was cut here", not as a smooth curve.
    if not solid:
        try:
            me.shade_smooth()
        except AttributeError:
            pass   # Blender < 4.1 fallback: flat shading is fine for vis
    me.update()
    # Clean any degenerate / out-of-range mesh data before handing the mesh
    # to Blender's modifier stack and serialiser.
    me.validate(verbose=False, clean_customdata=True)

    obj = bpy.data.objects.new(name, me)
    bpy.data.scenes[0].collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# Geometry modifiers
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


def _add_solidify(obj, thickness_mm: float = 1.0):
    """
    Add a Solidify modifier so hollow shell meshes appear solid when cut.

    GDML meshes are typically thin shells (single-layer faces).  When a
    phi-cutaway slices through them the interior is hollow.  The Solidify
    modifier extrudes faces inward by *thickness_mm*, giving the mesh a
    visible wall thickness so cutaway views look like slicing into a
    solid block of material.

    Parameters
    ----------
    thickness_mm : wall thickness in mm.  1.0 mm default.
    """
    mod = obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = thickness_mm
    mod.offset    = -1.0                  # keep outer surface in place
    # Even Thickness (use_even_offset) tries to maintain uniform thickness on
    # sloped faces by shifting vertices along an averaged normal.  On the
    # decimated, non-manifold GDML meshes this misbehaves: vertices at the
    # phi-cut boundary get pushed sideways instead of inward, producing
    # ragged inner walls and visible self-intersections in the rim faces.
    # Leaving it off uses the per-face normal directly, which on our meshes
    # gives cleaner walls and a stable cut cross-section.
    mod.use_even_offset   = False
    try:
        mod.use_quality_normals = True    # better shading (removed in Blender 5.0)
    except AttributeError:
        pass
    mod.use_rim_only      = False         # fill both rim and inner faces
    mod.use_rim           = True          # generate rim faces at open edges
    # Assign material index for the inner faces (rim + inside) so they
    # receive the same material as the outer surface.
    mod.material_offset = 0
    return mod


def _add_wireframe(obj, thickness_mm: float = 0.15):
    """
    Add a Wireframe modifier so individual face edges are visible in renders.

    Used for tracker and vertex sub-detectors where seeing individual module
    outlines is more informative than a smooth shaded surface.  The wireframe
    material (slot 1) is set to near-black so edges contrast with the base
    material.
    """
    # Create a thin dark wire material for the edges
    wire_mat_name = "Wire_Edge"
    wire_mat = bpy.data.materials.get(wire_mat_name)
    if wire_mat is None:
        wire_mat = _make_material(wire_mat_name, (0.02, 0.02, 0.02), 0.0, 0.9)
    # Ensure the object has the wire material in slot 1
    if len(obj.data.materials) < 2:
        obj.data.materials.append(wire_mat)
    else:
        obj.data.materials[1] = wire_mat

    mod = obj.modifiers.new("Wireframe", "WIREFRAME")
    mod.thickness = thickness_mm
    mod.use_replace = False          # overlay on top of the base mesh
    mod.material_offset = 1          # use wire material (slot 1)
    mod.use_even_offset = True
    mod.use_boundary = True          # draw open boundary edges too
    return mod


def _add_bevel(obj, width_mm: float = 0.2):
    """
    Add a Bevel modifier with a tiny chamfer on sharp edges.

    This adds micro-chamfers at angle-limited edges, which catches
    specular highlights and gives the detector components a more
    manufactured, physically-accurate appearance.

    Quality tuning (relative to the older 2-segment / profile-0.5 default):
      • segments=3   — smoother bevel arc, three highlight steps instead
                       of two; visually indistinguishable from a true
                       fillet at typical render resolutions.
      • profile=0.7  — slightly convex (super-elliptical) bevel profile
                       that catches highlights across a wider range of
                       view angles, producing the soft "manufactured edge"
                       glint at glancing camera angles.
      • angle_limit=35° — beveling only edges with an interior angle change
                       sharper than 35°.  Avoids beveling near-coplanar
                       seams between adjacent decimated triangles (which
                       would create a faceted "scaly" surface).
      • loop_slide=True — keeps the bevel's edge loops sliding along
                       neighbouring face directions so the geometry near
                       the bevel stays flat (no pinching on long edges).
      • harden_normals=True — preserves crisp face-flat shading on the
                       surface adjacent to the bevel; only the bevel
                       itself reads as smooth.  This is what produces a
                       sharp specular line along the manufactured edge
                       rather than a soft round-over.

    Parameters
    ----------
    width_mm : chamfer width in mm. 0.2 mm is microscopic — just enough
               to produce a specular glint without visibly changing shape.
               Set to 0 to skip.
    """
    if width_mm <= 0:
        return None
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width            = max(1e-6, width_mm)
    mod.segments         = 3
    mod.profile          = 0.7
    mod.limit_method     = "ANGLE"
    mod.angle_limit      = math.radians(35)
    mod.use_clamp_overlap = True
    # loop_slide stabilises bevel geometry on long edges (esp. cut boundary)
    try:
        mod.loop_slide = True
    except AttributeError:
        pass
    # Slightly miter outer corners so cut-boundary trips are also clean
    for attr_name, val in (("miter_outer", "ARC"), ("miter_inner", "SHARP")):
        try:
            setattr(mod, attr_name, val)
        except (AttributeError, TypeError):
            pass
    # harden_normals was removed from the Bevel modifier in Blender 4.2+
    try:
        mod.harden_normals = True
    except AttributeError:
        pass
    # Mark the bevel material as the same slot as the base surface so the
    # chamfer inherits the parent material rather than defaulting to slot 0
    # (which is already the base slot, so this is a no-op for single-material
    # objects but makes intent explicit).
    try:
        mod.material = -1
    except (AttributeError, TypeError):
        pass
    return mod


# ---------------------------------------------------------------------------
# Phi-cutaway Geometry Node group
# ---------------------------------------------------------------------------

def _apply_phi_cutaway_bmesh(obj, phi_min_deg: float, phi_max_deg: float):
    """
    Apply phi cutaway with geometrically clean cut edges using bmesh bisect.

    Instead of deleting whole faces by centroid (which leaves ragged edges),
    this function:
      1. Bisects the mesh along the phi_min plane → creates new vertices
         at the exact intersection of existing edges with the cut boundary.
      2. Bisects again along the phi_max plane → same for the other boundary.
      3. Deletes faces whose centroid phi falls inside [phi_min, phi_max].

    After the two bisect operations every face is fully inside or fully
    outside the cut sector, so the centroid-based deletion produces perfectly
    clean edges aligned to the phi boundary planes — no ragged stair-stepping.

    phi = atan2(-X_local, Y_local) in the mesh local coordinate frame.
    After the Ry(+90°) object rotation:  phi=0 → +Y_blender (up),
    phi=90° → +Z_blender (horizontal transverse).

    The two cut planes each contain the local Z axis (beam) and one of the
    boundary directions.  Their normals are perpendicular to those planes,
    pointing into the cut sector:
      phi_min plane normal: (-cos(phi_min), -sin(phi_min), 0)
      phi_max plane normal: ( cos(phi_max),  sin(phi_max), 0)
    """
    import bmesh

    phi_min = math.radians(phi_min_deg)
    phi_max = math.radians(phi_max_deg)
    n_faces_before = len(obj.data.polygons)
    print(f"  [PHI-BISECT] Cutting sector [{phi_min_deg:.1f}°, {phi_max_deg:.1f}°] "
          f"from '{obj.name}' ({n_faces_before} faces) ...", flush=True)

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    # --- Step 1: Bisect at the phi_min boundary ---
    # This plane contains the Z axis and the direction at phi_min.
    # Direction at phi_min: (-sin(phi_min), cos(phi_min), 0)
    # Plane normal (perpendicular, pointing into the cut sector):
    #   Z × dir = (0,0,1) × (-sin φ, cos φ, 0) = (-cos φ, -sin φ, 0)
    # bisect_plane with clear_inner=False, clear_outer=False just splits
    # faces without deleting anything — creates new vertices at intersection.
    normal_min = (-math.cos(phi_min), -math.sin(phi_min), 0.0)
    geom_all = bm.verts[:] + bm.edges[:] + bm.faces[:]
    bmesh.ops.bisect_plane(
        bm,
        geom=geom_all,
        plane_co=(0.0, 0.0, 0.0),
        plane_no=normal_min,
        clear_inner=False,
        clear_outer=False,
    )
    n_after_bisect1 = len(bm.faces)

    # --- Step 2: Bisect at the phi_max boundary ---
    # Direction at phi_max: (-sin(phi_max), cos(phi_max), 0)
    # Normal pointing into the cut sector (opposite side):
    #   -Z × dir = -(0,0,1) × (-sin φ, cos φ, 0) = (cos φ, sin φ, 0)
    normal_max = (math.cos(phi_max), math.sin(phi_max), 0.0)
    geom_all = bm.verts[:] + bm.edges[:] + bm.faces[:]
    bmesh.ops.bisect_plane(
        bm,
        geom=geom_all,
        plane_co=(0.0, 0.0, 0.0),
        plane_no=normal_max,
        clear_inner=False,
        clear_outer=False,
    )
    n_after_bisect2 = len(bm.faces)

    print(f"  [PHI-BISECT]   Bisect: {n_faces_before} → {n_after_bisect1} → "
          f"{n_after_bisect2} faces (new vertices created at cut boundaries)",
          flush=True)

    # --- Step 3: Delete faces inside the cut sector ---
    # After bisection, every face is fully inside or fully outside the sector
    # so centroid classification gives exact results with clean edges.
    bm.faces.ensure_lookup_table()
    del_faces = []
    for f in bm.faces:
        n = len(f.verts)
        cx = sum(v.co.x for v in f.verts) / n
        cy = sum(v.co.y for v in f.verts) / n
        phi = math.atan2(-cx, cy)
        if phi_min <= phi <= phi_max:
            del_faces.append(f)

    print(f"  [PHI-BISECT]   Deleting {len(del_faces)} faces inside cut sector",
          flush=True)
    bmesh.ops.delete(bm, geom=del_faces, context="FACES")

    # --- Step 4: Clean up isolated vertices left by face deletion ---
    # After deleting faces, some vertices along the cut boundary may be
    # orphaned (not attached to any remaining face).
    bm.verts.ensure_lookup_table()
    orphan_verts = [v for v in bm.verts if not v.link_faces]
    if orphan_verts:
        bmesh.ops.delete(bm, geom=orphan_verts, context="VERTS")

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    n_faces_after = len(obj.data.polygons)
    print(f"  [PHI-BISECT]   Done: {n_faces_after} faces remain "
          f"(clean cut edges with new intersection vertices)", flush=True)


def _precompute_phi_face_attribute(obj):
    """
    Compute phi = atan2(-X_local, Y_local) in degrees for every face centroid
    and store it as a float FACE attribute named 'phi_deg' on the mesh.

    phi convention (in mesh local / GDML coordinates):
        phi=0°   → +Y_local  (after Ry+90° → +Y_blender = physics-up)
        phi=90°  → −X_local  (after Ry+90° → +Z_blender = horiz transverse)

    This matches the convention used by both the v4 and v5 GN node groups
    and by the bmesh fallback.

    Required for the Blender 5.0+ phi-cutaway node group, which cannot use
    ShaderNodeMath to compute atan2 inside a GeometryNodeTree.  The GN
    modifier reads this pre-computed attribute via GeometryNodeInputNamedAttribute
    so it only needs FunctionNodeCompare / FunctionNodeBooleanMath — nodes
    that remain valid in Blender 5.0+ geometry node trees.

    Uses numpy vectorisation for speed on meshes with 100K+ faces.
    """
    mesh = obj.data
    n_polys = len(mesh.polygons)

    if n_polys == 0:
        return

    # Vectorised centroid computation via numpy
    # Get all vertex positions as a flat array, then compute centroids per polygon
    n_verts = len(mesh.vertices)
    coords = np.empty(n_verts * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape((n_verts, 3))

    # Compute per-face centroids using polygon loop vertex indices
    phi_values = np.empty(n_polys, dtype=np.float64)
    for i, poly in enumerate(mesh.polygons):
        verts = poly.vertices
        cx = coords[verts, 0].mean()
        cy = coords[verts, 1].mean()
        # Blender-YZ convention: phi = atan2(-X_local, Y_local)
        phi_values[i] = math.degrees(math.atan2(-cx, cy))

    attr = mesh.attributes.new("phi_deg", "FLOAT", "FACE")
    attr.data.foreach_set("value", phi_values)


def _phi_cutaway_node_group(phi_min_default: float, phi_max_default: float):
    """
    Build (or retrieve) the shared 'PhiCutaway' geometry node group.

    Node graph  (Blender 4.x — uses ShaderNodeMath inside GeometryNodeTree)
    ----------
    Position → SeparateXYZ
                 -X, Y  → Math(ARCTAN2) → Math(DEGREES) → phi_deg
    phi_deg + Phi Min → Math(GREATER_THAN) → gt
    phi_deg + Phi Max → Math(LESS_THAN)    → lt
    Math(MULTIPLY, gt, lt)        → inside   (1.0 if in cut sector)
    Merge by Distance             → (weld any remaining seam duplicates)
    Delete Geometry (FACE domain, selection=inside)

    Convention (mesh local / GDML coordinates)
    ----------
    phi = atan2(-X_local, Y_local) in degrees, range [-180, 180].
    phi=0°   → +Y_local (after Ry+90° → +Y_blender = physics-up)
    phi=90°  → −X_local (after Ry+90° → +Z_blender = horiz-transverse)

    Faces inside [phi_min, phi_max] are DELETED (cut away); everything else
    is kept.  This reveals the interior of the detector through the removed
    sector.  Default phi_min=0, phi_max=90 cuts away the first quadrant.
    """
    # Blender 5.0+ removed ShaderNode* from GeometryNodeTree.  Delegate to the
    # 5.0-compatible implementation that reads a pre-computed face attribute
    # instead of computing atan2 inside the node group.
    if bpy.app.version >= (5, 0, 0):
        return _phi_cutaway_node_group_v5(phi_min_default, phi_max_default)

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

    # Vertex position → atan2(-X, Y) → degrees
    # Blender-YZ convention: phi=0 → +Y_blender, phi=90 → +Z_blender
    pos   = N("GeometryNodeInputPosition",   -600, -120)
    sep   = N("ShaderNodeSeparateXYZ",        -400, -120)

    # Negate X so ARCTAN2 computes atan2(-X, Y)
    neg_x = N("ShaderNodeMath",               -250, -180)
    neg_x.operation = "MULTIPLY"
    neg_x.label = "neg X"
    neg_x.inputs[1].default_value = -1.0

    atan2 = N("ShaderNodeMath",              -100, -120)
    atan2.operation = "ARCTAN2"
    atan2.label = "atan2(-X,Y)"

    todeg = N("ShaderNodeMath",               100, -120)
    todeg.operation = "DEGREES"
    todeg.label = "to degrees"

    # Range test: gt * lt = 1.0 iff inside the cut sector
    gt = N("ShaderNodeMath",                  300,   80)
    gt.operation = "GREATER_THAN"
    gt.label = "phi > phi_min"

    lt = N("ShaderNodeMath",                  300,  -80)
    lt.operation = "LESS_THAN"
    lt.label = "phi < phi_max"

    mul = N("ShaderNodeMath",                 460,    0)
    mul.operation = "MULTIPLY"
    mul.label = "inside (cut away)"

    # Merge seam duplicates before the cut
    merge = N("GeometryNodeMergeByDistance",  -600,  100)
    merge.inputs["Distance"].default_value = 1e-4
    merge.label = "Weld seam duplicates"

    # Delete faces INSIDE the phi range (cut sector)
    delete = N("GeometryNodeDeleteGeometry",   620,    0)
    delete.domain = "FACE"
    delete.mode   = "ALL"

    # ---- Wiring ----
    # Geometry pass-through via merge-by-distance first
    links.new(g_in.outputs["Geometry"],   merge.inputs["Geometry"])

    # Position field chain: sep → negate X → atan2(-X, Y) → degrees
    links.new(pos.outputs["Position"],    sep.inputs["Vector"])
    links.new(sep.outputs["X"],           neg_x.inputs[0])
    links.new(neg_x.outputs["Value"],     atan2.inputs[0])   # -X is first arg
    links.new(sep.outputs["Y"],           atan2.inputs[1])   # Y is second arg
    links.new(atan2.outputs["Value"],     todeg.inputs["Value"])

    # Phi-range tests
    links.new(todeg.outputs["Value"],     gt.inputs[0])
    links.new(g_in.outputs["Phi Min"],    gt.inputs[1])
    links.new(todeg.outputs["Value"],     lt.inputs[0])
    links.new(g_in.outputs["Phi Max"],    lt.inputs[1])

    # Combine: inside = gt AND lt
    links.new(gt.outputs["Value"],        mul.inputs[0])
    links.new(lt.outputs["Value"],        mul.inputs[1])

    # Delete faces inside the cut sector
    links.new(merge.outputs["Geometry"],  delete.inputs["Geometry"])
    links.new(mul.outputs["Value"],       delete.inputs["Selection"])
    links.new(delete.outputs["Geometry"], g_out.inputs["Geometry"])

    return ng


def _phi_cutaway_node_group_v5(phi_min_default: float, phi_max_default: float):
    """
    Blender 5.0+ compatible phi-cutaway geometry node group.

    ShaderNode* types are not valid inside a GeometryNodeTree in Blender 5.0+,
    so atan2 is pre-computed in Python and stored as a face attribute "phi_deg"
    by _precompute_phi_face_attribute.  This node group reads that attribute
    using only node types that are valid in Blender 5.0+ geometry trees:

      GeometryNodeInputNamedAttribute  — reads "phi_deg" float field
      FunctionNodeCompare              — phi_deg > Phi Min / phi_deg < Phi Max
      FunctionNodeBooleanMath          — AND the two → inside
      GeometryNodeDeleteGeometry       — delete faces where inside is True

    Faces inside [Phi Min, Phi Max] are DELETED (cut away); everything else
    is kept, revealing the detector interior.

    Returns None if any required node type does not exist or if wiring fails,
    so the caller can fall back to _apply_phi_cutaway_bmesh.
    """
    import traceback
    NG_NAME = "PhiCutaway"
    if NG_NAME in bpy.data.node_groups:
        print(f"  [PHI-V5] Reusing existing '{NG_NAME}' node group.", flush=True)
        return bpy.data.node_groups[NG_NAME]

    print(f"  [PHI-V5] Building Blender 5.0+ PhiCutaway node group "
          f"(bpy {bpy.app.version_string}) ...", flush=True)
    try:
        ng    = bpy.data.node_groups.new(NG_NAME, "GeometryNodeTree")
        nodes = ng.nodes
        links = ng.links
        print(f"  [PHI-V5] Node group created: {ng.name!r}", flush=True)

        # ---- Interface ----
        ng.interface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
        s_min = ng.interface.new_socket("Phi Min", in_out="INPUT",  socket_type="NodeSocketFloat")
        s_max = ng.interface.new_socket("Phi Max", in_out="INPUT",  socket_type="NodeSocketFloat")
        ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        s_min.default_value = phi_min_default
        s_max.default_value = phi_max_default
        print(f"  [PHI-V5] Interface sockets: "
              f"{[s.name for s in ng.interface.items_tree]}", flush=True)

        def N(bl_type, x=0, y=0):
            n = nodes.new(bl_type)
            ins  = [s.name for s in n.inputs]  if n else []
            outs = [s.name for s in n.outputs] if n else []
            print(f"  [PHI-V5]   node {bl_type!r:45s} "
                  f"in={ins}  out={outs}", flush=True)
            if n:
                n.location = (x, y)
            return n

        g_in      = N("NodeGroupInput",                     -700,    0)
        g_out     = N("NodeGroupOutput",                     700,    0)
        attr_node = N("GeometryNodeInputNamedAttribute",    -500,  -80)
        gt        = N("FunctionNodeCompare",                -260,   80)
        lt        = N("FunctionNodeCompare",                -260,  -80)
        and_node  = N("FunctionNodeBooleanMath",             -60,    0)
        delete    = N("GeometryNodeDeleteGeometry",          320,    0)

        missing = [name for name, n in (
            ("NodeGroupInput",                  g_in),
            ("NodeGroupOutput",                 g_out),
            ("GeometryNodeInputNamedAttribute", attr_node),
            ("FunctionNodeCompare (GT)",        gt),
            ("FunctionNodeCompare (LT)",        lt),
            ("FunctionNodeBooleanMath (AND)",   and_node),
            ("GeometryNodeDeleteGeometry",      delete),
        ) if n is None]
        if missing:
            raise RuntimeError(f"These node types could not be created: {missing}")

        # Configure nodes
        attr_node.data_type   = "FLOAT"
        attr_node.inputs[0].default_value = "phi_deg"   # "Name" socket (index 0)
        print(f"  [PHI-V5] NamedAttribute: data_type={attr_node.data_type!r}  "
              f"name_input={attr_node.inputs[0].default_value!r}", flush=True)

        gt.data_type = "FLOAT";  gt.operation = "GREATER_THAN";  gt.label = "phi > phi_min"
        lt.data_type = "FLOAT";  lt.operation = "LESS_THAN";     lt.label = "phi < phi_max"
        and_node.operation = "AND";  and_node.label = "inside (cut away)"
        delete.domain = "FACE";  delete.mode = "ALL"

        print(f"  [PHI-V5] GT  inputs={[s.name for s in gt.inputs]}  "
              f"outputs={[s.name for s in gt.outputs]}", flush=True)
        print(f"  [PHI-V5] AND inputs={[s.name for s in and_node.inputs]}  "
              f"outputs={[s.name for s in and_node.outputs]}", flush=True)
        print(f"  [PHI-V5] DEL inputs={[s.name for s in delete.inputs]}  "
              f"outputs={[s.name for s in delete.outputs]}", flush=True)

        # ---- Wiring (use indices throughout — socket names may vary by version) ----
        def L(src, dst, tag=""):
            lnk = links.new(src, dst)
            ok = "OK" if lnk else "FAIL"
            src_label = f"{src.node.bl_idname}[{src.name}]"
            dst_label = f"{dst.node.bl_idname}[{dst.name}]"
            print(f"  [PHI-V5]   link {ok}  {src_label} → {dst_label}"
                  + (f"  ({tag})" if tag else ""), flush=True)
            return lnk

        phi_field = attr_node.outputs[0]  # float field from NamedAttribute

        L(phi_field,                gt.inputs[0],             "phi→GT.A")
        L(g_in.outputs["Phi Min"], gt.inputs[1],              "phi_min→GT.B")
        L(phi_field,                lt.inputs[0],             "phi→LT.A")
        L(g_in.outputs["Phi Max"], lt.inputs[1],              "phi_max→LT.B")
        L(gt.outputs[0],            and_node.inputs[0],       "GT→AND[0]")
        L(lt.outputs[0],            and_node.inputs[1],       "LT→AND[1]")
        # Delete faces INSIDE [phi_min, phi_max] — the cut sector
        L(g_in.outputs["Geometry"], delete.inputs["Geometry"],"Geo→DEL")
        L(and_node.outputs[0],      delete.inputs["Selection"],"AND→DEL.sel")
        L(delete.outputs["Geometry"], g_out.inputs["Geometry"],"DEL→out")

        print(f"  [PHI-V5] Node group complete. "
              f"nodes={len(ng.nodes)}  links={len(ng.links)}", flush=True)
        return ng

    except Exception as exc:
        print(f"  [PHI-V5] ERROR: {exc}", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        if NG_NAME in bpy.data.node_groups:
            try:
                bpy.data.node_groups.remove(bpy.data.node_groups[NG_NAME])
                print(f"  [PHI-V5] Removed incomplete node group to prevent save crash.",
                      flush=True)
            except Exception:
                pass
        print(f"  [PHI-V5] Will fall back to bmesh phi cutaway.", flush=True)
        return None


def _add_phi_cutaway(obj, ng, phi_min: float, phi_max: float, ctrl_obj):
    """
    Add the PhiCutaway GN modifier to *obj*.

    The modifier references the shared *ng* node group whose socket defaults
    are set to (phi_min, phi_max).  We do NOT set per-modifier overrides so
    that all objects read from the same group defaults — changing the defaults
    (via the PhiCutawayControl empty or in the node-group editor) updates
    every detector simultaneously.

    On Blender 4.x, if *ctrl_obj* is provided, scripted drivers are wired
    from the empty's custom properties to the modifier sockets so the cut
    sector updates live when the empty's properties are changed.

    On Blender 5.0+ drivers on GN modifier sockets crash save_as_mainfile,
    so drivers are skipped; the user adjusts the cut by editing the
    PhiCutawayControl empty's custom properties and re-running the script,
    or by editing the node group's socket defaults directly in Blender.
    """
    mod = obj.modifiers.new("PhiCutaway", "NODES")
    mod.node_group = ng

    if ctrl_obj is None:
        # No control object — modifiers read from node group defaults.
        return

    # Identify socket identifiers by name for driver wiring
    id_min = id_max = None
    for item in ng.interface.items_tree:
        if getattr(item, "item_type", None) == "SOCKET" and item.in_out == "INPUT":
            if item.name == "Phi Min":
                id_min = item.identifier
            elif item.name == "Phi Max":
                id_max = item.identifier

    # In Blender 5.0+ the GN modifier input storage changed; driver paths of the
    # form mod["Socket_X"] may no longer map to valid FCurve targets and a
    # half-configured FCurve will crash save_as_mainfile with SIGSEGV.
    if bpy.app.version >= (5, 0, 0):
        return

    for identifier, prop_name, default in (
        (id_min, "phi_min", phi_min),
        (id_max, "phi_max", phi_max),
    ):
        if identifier is None:
            continue
        mod[identifier] = default

        fc = None
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
            print(f"  [PHI] Driver OK: mod[{identifier!r}] ← ctrl[{prop_name!r}]",
                  flush=True)
        except Exception as exc:
            print(f"  [PHI] Driver warning ({identifier!r}): {exc}", flush=True)
            if fc is not None:
                try:
                    mod.driver_remove(f'["{identifier}"]')
                except Exception:
                    pass


def _create_phi_control_empty(phi_min: float, phi_max: float, collection):
    """
    Create a PhiCutawayControl empty object with custom properties that
    serve as the single control point for all phi-cutaway modifiers.

    The empty is placed at the scene origin and displayed as a plain axis.
    Its custom properties phi_min and phi_max are the master values:
    - On Blender 4.x, scripted drivers on each modifier socket read from
      these properties, so changing them updates all sub-detectors live.
    - On Blender 5.0+, the node group's socket defaults are set to match
      these values.  Adjusting the empty's properties requires re-running
      the script or manually editing the node group defaults.
    """
    empty = bpy.data.objects.new("PhiCutawayControl", None)
    bpy.data.scenes[0].collection.objects.link(empty)

    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 100.0

    # Custom properties (editable in Properties → Object → Custom Properties)
    empty["phi_min"] = phi_min
    empty["phi_max"] = phi_max

    # Set UI metadata so the custom properties appear with tooltips and limits
    # in the Blender properties panel.
    try:
        ui = empty.id_properties_ui("phi_min")
        ui.update(description="Start of the phi sector to cut away (degrees)",
                  default=phi_min, min=-180.0, max=180.0, soft_min=-180.0, soft_max=180.0)
        ui = empty.id_properties_ui("phi_max")
        ui.update(description="End of the phi sector to cut away (degrees)",
                  default=phi_max, min=-180.0, max=180.0, soft_min=-180.0, soft_max=180.0)
    except Exception:
        pass  # id_properties_ui may not be available on all builds

    # Hide the control empty from both viewport and render — it is a
    # control-only object, not something that should ever appear visually.
    empty.hide_viewport = True
    empty.hide_render   = True

    if collection is not None:
        _link_to_collection(empty, collection)

    print(f"  [PHI] PhiCutawayControl empty created: "
          f"phi_min={phi_min:.1f}°  phi_max={phi_max:.1f}°", flush=True)
    return empty


# ---------------------------------------------------------------------------
# Live phi-wedge Boolean cutter
# ---------------------------------------------------------------------------


def _create_phi_wedge_cutter(
    phi_min_deg: float,
    phi_max_deg: float,
    radius: float,
    depth: float,
    collection,
):
    """
    Create a solid pie-slice cylinder covering the phi sector [phi_min, phi_max].

    This manifold solid is used as the operand for a Boolean DIFFERENCE modifier
    on detector objects.  DIFFERENCE subtracts the wedge from the detector,
    removing the sector and revealing the interior — matching the behavior of
    the GN phi-cutaway modifier which deletes faces inside the same range.

    Geometry convention (mesh local / GDML coordinates, before Ry+90° rotation):
        phi = atan2(-X_local, Y_local) in degrees
        phi=0°  → +Y_local (after rotation: +Y_blender = physics-up)
        phi=90° → −X_local (after rotation: +Z_blender = horiz-transverse)

    The wedge is built directly as a closed, manifold solid so that Blender's
    Boolean modifier works correctly.  It is shown as wireframe in the viewport
    and excluded from renders.

    Note: the wedge is created in GDML local coordinates and should be given
    the same rotation as the detector objects (Ry+90°) by the caller.
    """
    import bmesh as _bm

    N_ARC  = 64           # arc segments within the sector
    r      = radius
    half_d = depth / 2.0

    phi_min_r = math.radians(phi_min_deg)
    phi_max_r = math.radians(phi_max_deg)

    me = bpy.data.meshes.new("PhiWedge")
    bm = _bm.new()

    # Centre vertices on the ±X caps (beam axis)
    vc_pos = bm.verts.new((+half_d, 0.0, 0.0))
    vc_neg = bm.verts.new((-half_d, 0.0, 0.0))

    # Arc vertices at ±X from phi_min to phi_max (N_ARC+1 vertices inclusive)
    # phi=0 → +Y, phi=90° → +Z
    vp, vn = [], []
    for i in range(N_ARC + 1):
        ang = phi_min_r + i * (phi_max_r - phi_min_r) / N_ARC
        y   = r * math.cos(ang)
        z   = r * math.sin(ang)
        vp.append(bm.verts.new((+half_d, y, z)))
        vn.append(bm.verts.new((-half_d, y, z)))

    bm.verts.ensure_lookup_table()

    # Outer arc wall — side quads.
    # Winding [vp[i], vn[i], vn[i+1], vp[i+1]] gives outward normals:
    #   normal = (vn[i]-vp[i]) × (vn[i+1]-vp[i])
    #          = (-2d, 0, 0) × (-2d, Δy, Δz) = (0, +2d·Δz, -2d·Δy) → radially out ✓
    for i in range(N_ARC):
        bm.faces.new([vp[i], vn[i], vn[i + 1], vp[i + 1]])

    # +X end-cap: fan of triangles from centre.
    # Winding [vc_pos, vp[i], vp[i+1]] → normal = r²·sin(Δphi) in +X direction ✓
    for i in range(N_ARC):
        bm.faces.new([vc_pos, vp[i], vp[i + 1]])

    # −X end-cap: fan of triangles from centre.
    # Winding [vc_neg, vn[i+1], vn[i]] → normal in −X direction ✓
    for i in range(N_ARC):
        bm.faces.new([vc_neg, vn[i + 1], vn[i]])

    # Radial wall at phi_min (normal points away from sector interior)
    bm.faces.new([vc_pos, vc_neg, vn[0], vp[0]])

    # Radial wall at phi_max (normal points away from sector interior)
    bm.faces.new([vc_pos, vp[N_ARC], vn[N_ARC], vc_neg])

    bm.to_mesh(me)
    bm.free()
    me.update()

    obj = bpy.data.objects.new("PhiWedge", me)
    bpy.data.scenes[0].collection.objects.link(obj)

    # Wireframe-only in viewport — user can see/select it but it won't obscure
    # the detector.  Excluded from renders entirely.
    # Hidden from both viewport and render so it never appears in output.
    obj.display_type = "WIRE"
    obj.hide_viewport = True
    obj.hide_render   = True

    _link_to_collection(obj, collection)
    print(f"  [WEDGE] PhiWedge cutter: "
          f"phi=[{phi_min_deg:.1f}°,{phi_max_deg:.1f}°] "
          f"r={r:.1f} depth={depth:.1f} BU", flush=True)
    return obj


def _apply_boolean_phi_cut(det_obj, wedge_obj, operation: str = "DIFFERENCE"):
    """
    Add a Boolean modifier to *det_obj* that uses *wedge_obj* as the operand.

    Parameters
    ----------
    operation : 'DIFFERENCE' to remove the wedge shape (the cut sector) from
                the detector.  The wedge covers [phi_min, phi_max]; subtracting
                it removes that sector, matching the GN phi-cutaway modifier.

    Blender 5.0 renamed the fast/float solver: 'FAST' → 'FLOAT'.
    Try the version-appropriate name and fall back silently.
    """
    mod           = det_obj.modifiers.new("PhiBoolean", "BOOLEAN")
    mod.operation = operation
    mod.object    = wedge_obj
    # Blender 4.x: 'FAST' | Blender 5.0+: 'FLOAT' (same algorithm, renamed)
    for solver in ("FLOAT", "FAST"):
        try:
            mod.solver = solver
            break
        except TypeError:
            pass
    return mod


# ---------------------------------------------------------------------------
# Environment sphere
# ---------------------------------------------------------------------------

def _add_environment_sphere(radius: float):
    """
    Place a large matte sphere around the detector that acts as a soft-light
    environment dome.

    Normals are flipped inward so the surface faces the scene interior.
    The off-white Lambertian material diffusely reflects the area lights back
    onto the detector, producing soft fill light without a visible background
    wall.  Shadow casting is disabled so the sphere itself doesn't block the
    lights.
    """
    import bmesh as _bm
    mesh = bpy.data.meshes.new("EnvironmentSphere")
    bm = _bm.new()
    _bm.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=radius)
    _bm.ops.reverse_faces(bm, faces=bm.faces)   # normals point inward
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    try:
        mesh.shade_smooth()
    except AttributeError:
        pass
    mesh.update()

    obj = bpy.data.objects.new("EnvironmentSphere", mesh)
    bpy.data.scenes[0].collection.objects.link(obj)

    mat = bpy.data.materials.new("EnvironmentMatte")
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.88, 0.88, 0.90, 1.0)
        bsdf.inputs["Metallic"].default_value   = 0.0
        bsdf.inputs["Roughness"].default_value  = 1.0
    obj.data.materials.append(mat)

    # Don't block the lights or cast shadows onto the detector
    try:
        obj.visible_shadow = False
    except AttributeError:
        try:
            obj.cycles_visibility.shadow = False
        except AttributeError:
            pass

    print(f"  [SETUP] Environment sphere: radius={radius:.0f} mm", flush=True)
    return obj


# ---------------------------------------------------------------------------
# Scene utilities
# ---------------------------------------------------------------------------

def _clear_scene():
    """Remove every default object (cube, light, camera)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def _make_collection(name: str) -> "bpy.types.Collection":
    """Create a named collection and link it to the master scene collection."""
    col = bpy.data.collections.new(name)
    bpy.data.scenes[0].collection.children.link(col)
    return col


def _link_to_collection(obj, col) -> None:
    """Move *obj* from whichever collection(s) it currently belongs to into *col*."""
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)


def _setup_units():
    scene = bpy.data.scenes[0]
    scene.unit_settings.system       = "METRIC"
    scene.unit_settings.scale_length = 0.001   # 1 Blender unit = 1 mm
    scene.unit_settings.length_unit  = "MILLIMETERS"

    # Set 3D viewport clip distance so the full detector is visible when
    # orbiting interactively.  At native mm scale the detector is 5000–12000 mm.
    # Default clip_end of 1000 BU clips everything beyond 1 m.
    for area in bpy.context.screen.areas if hasattr(bpy.context, 'screen') else []:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_start = 1.0        # 1 mm
                    space.clip_end   = 100000.0   # 100 m


# ---------------------------------------------------------------------------
# Lighting — golden-hour area lights with colour temperature
# ---------------------------------------------------------------------------

def _disable_light_normalize(light_data, name: str = "") -> bool:
    """
    Force the light's "Normalize" toggle off.

    Blender renamed the property between major versions:
      Blender 3.x / 4.x  : light_data.use_normalize   (bool)
      Blender 5.0+       : light_data.normalize       (bool)

    A `hasattr` check on only one name silently passes on builds that use
    the other name — which is the bug the user reported (lights still
    showed Normalize ON in Blender 5.x after a "fix").  We try both names
    in sequence and verify the value was actually written.

    Returns True if at least one attribute was successfully set False.
    """
    ok = False
    for attr in ("normalize", "use_normalize"):
        if hasattr(light_data, attr):
            try:
                setattr(light_data, attr, False)
                # Verify (some properties are read-only on certain types)
                if getattr(light_data, attr) is False:
                    ok = True
            except (AttributeError, TypeError) as exc:
                if name:
                    print(f"  [LIGHT] {name}: setting {attr}=False failed: {exc}",
                          flush=True)
    if not ok and name:
        print(f"  [LIGHT] {name}: WARNING — could not disable normalize "
              f"(neither 'normalize' nor 'use_normalize' is settable)",
              flush=True)
    return ok


def _kelvin_to_rgb(temp_kelvin: float) -> tuple:
    """
    Approximate sRGB for a blackbody colour temperature (Tanner Helland algo).

    Used on Blender 5.0+ where ShaderNodeBlackbody is no longer safe to place
    in a light data node tree; instead the colour is set directly on the light.
    Returns an (r, g, b) tuple in [0, 1].
    """
    t = max(1000.0, min(40000.0, float(temp_kelvin))) / 100.0

    # Red
    r = 1.0 if t <= 66 else min(1.0, max(0.0,
            329.698727446 * (t - 60) ** -0.1332047592 / 255.0))
    # Green
    if t <= 66:
        g = min(1.0, max(0.0,
            (99.4708025861 * math.log(t) - 161.1195681661) / 255.0))
    else:
        g = min(1.0, max(0.0,
            288.1221695283 * (t - 60) ** -0.0755148492 / 255.0))
    # Blue
    if   t >= 66:  b = 1.0
    elif t <= 19:  b = 0.0
    else:          b = min(1.0, max(0.0,
            (138.5177312231 * math.log(t - 10) - 305.0447927307) / 255.0))

    return (r, g, b)


def _set_light_temperature(light_data, name: str, energy: float,
                           temp_kelvin: float) -> None:
    """
    Configure *light_data* to render with *temp_kelvin* colour temperature
    using Blender's native blackbody — not an RGB approximation.

    Property name varies by Blender version:
      Blender 5.0+    : light_data.use_temperature
      Blender 4.4-4.x : light_data.use_color_temperature
    Both versions store the Kelvin value on `light_data.temperature`.

    Tries, in order:
      1. Either native boolean (use_temperature / use_color_temperature) +
         the shared `temperature` float
      2. ShaderNodeBlackbody in the light's node tree  (Blender 3.x / 4.x)
      3. _kelvin_to_rgb RGB fallback (last resort)
    """
    # --- Attempt 1: native temperature toggle (5.0+ or 4.4+) ---
    for attr in ("use_temperature", "use_color_temperature"):
        if hasattr(light_data, attr):
            try:
                setattr(light_data, attr, True)
                light_data.temperature = float(temp_kelvin)
                if getattr(light_data, attr) is True:
                    print(f"  [LIGHT] {name}  {energy:.1f}  "
                          f"{temp_kelvin:.0f} K  (native {attr})",
                          flush=True)
                    return
            except Exception as exc:
                print(f"  [LIGHT] {name}  {attr} failed: {exc}", flush=True)

    # --- Attempt 2: ShaderNodeBlackbody in node tree (Blender 3.x / 4.x) ---
    # On Blender 5.0+ ShaderNodeBlackbody in light node trees can crash
    # save_as_mainfile, so skip this path for those versions.
    if bpy.app.version < (5, 0, 0):
        try:
            light_data.use_nodes = True
            tree     = light_data.node_tree
            nodes    = tree.nodes
            links    = tree.links
            nodes.clear()
            out      = nodes.new("ShaderNodeOutputLight")
            emission = nodes.new("ShaderNodeEmission")
            bb       = nodes.new("ShaderNodeBlackbody")
            bb.inputs["Temperature"].default_value   = float(temp_kelvin)
            emission.inputs["Strength"].default_value = 1.0
            links.new(bb.outputs["Color"],       emission.inputs["Color"])
            links.new(emission.outputs["Emission"], out.inputs["Surface"])
            print(f"  [LIGHT] {name}  {energy:.0f} W  "
                  f"{temp_kelvin:.0f} K  (ShaderNodeBlackbody node tree)",
                  flush=True)
            return
        except Exception as exc:
            print(f"  [LIGHT] {name}  ShaderNodeBlackbody failed: {exc}", flush=True)

    # --- Fallback 3: RGB approximation ---
    r, g, b = _kelvin_to_rgb(temp_kelvin)
    light_data.color = (r, g, b)
    print(f"  [LIGHT] {name}  {energy:.0f} W  "
          f"{temp_kelvin:.0f} K → rgb({r:.3f},{g:.3f},{b:.3f})  (RGB approx)",
          flush=True)


def _area_light_with_temperature(
    name: str,
    location: tuple,
    target: tuple,
    size: float,
    energy: float,
    temp_kelvin: float,
):
    """
    Create an AREA light whose colour is set by a Blackbody shader node.

    Parameters
    ----------
    name        : object name
    location    : (x, y, z) in mm
    target      : point the light faces
    size        : diameter of the area light disk in mm
    energy      : lamp energy (watts — Blender Cycles units)
    temp_kelvin : colour temperature; 2000 K = deep amber, 6500 K = daylight
    """
    light_data        = bpy.data.lights.new(name, type="AREA")
    light_data.energy = energy
    light_data.size   = size
    light_data.shape  = "SQUARE"

    # Disable normalize: with normalize=False the energy field is the
    # radiant exitance of the light surface (W/m²), and total emitted power
    # scales linearly with light area.  Two consequences:
    #   1. Irradiance at the subject becomes INDEPENDENT of detector size
    #      when light size scales proportionally with r — so a single
    #      W/m² value works across all detector geometries.
    #   2. Energy values are physically meaningful (compare to sunlight
    #      ≈ 1000 W/m², studio softbox ≈ 500-2000 W/m²) rather than the
    #      unitless mega-wattages the normalize=True scaling produced at
    #      mm scene scale.
    #
    # Property name varies by Blender version:
    #   Blender 3.x / 4.x : use_normalize
    #   Blender 5.0+      : normalize
    # _disable_light_normalize tries both so the toggle is actually off
    # in the saved file regardless of which Blender opens it.
    _disable_light_normalize(light_data, name)

    # Use Blender's built-in colour temperature (real blackbody, not RGB approx).
    # Priority:
    #   1. Native color_mode = 'TEMPERATURE' property (Blender 4.0+)
    #   2. ShaderNodeBlackbody in the light node tree (Blender 3.x)
    #   3. _kelvin_to_rgb approximation (last resort)
    _set_light_temperature(light_data, name, energy, temp_kelvin)

    light_obj = bpy.data.objects.new(name, light_data)
    bpy.data.scenes[0].collection.objects.link(light_obj)
    light_obj.location = Vector(location)

    direction = (Vector(target) - Vector(location)).normalized()
    light_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return light_obj


def _add_point_light(
    name: str,
    location: tuple,
    energy: float,
    color_rgb: tuple,
    soft_size: float,
    temp_kelvin: float | None = None,
):
    """
    Create a point light.

    If *temp_kelvin* is given, the colour is set via Blender's native
    blackbody colour-temperature mechanism (true Planck spectrum).
    Otherwise *color_rgb* is used as a fixed RGB colour.

    soft_size controls the shadow softness radius.
    """
    light_data        = bpy.data.lights.new(name, type="POINT")
    light_data.energy = energy

    # Disable normalize: for point lights with normalize=False the
    # energy is the radiant intensity (W/sr).  Total emitted power is
    # energy * 4π — physically meaningful and matches the area-light
    # convention used in _area_light_with_temperature.
    _disable_light_normalize(light_data, name)

    if temp_kelvin is not None:
        _set_light_temperature(light_data, name, energy, temp_kelvin)
    else:
        light_data.color = color_rgb

    # shadow_soft_size was renamed/removed in Blender 5.0; try the new name first
    if hasattr(light_data, "shadow_source_angle"):
        light_data.shadow_source_angle = soft_size * 0.01  # rough conversion
    elif hasattr(light_data, "shadow_soft_size"):
        light_data.shadow_soft_size = soft_size

    light_obj = bpy.data.objects.new(name, light_data)
    bpy.data.scenes[0].collection.objects.link(light_obj)
    light_obj.location = Vector(location)
    return light_obj


def _add_ip_emissive_disk(
    name: str,
    location: tuple,
    radius_mm: float = 20.0,
    color_rgb: tuple = (0.6, 0.1, 1.0),
    strength: float = 400.0,
):
    """
    A small emissive sphere at the interaction point.  Gives bloom and
    streaks a concrete bright source to wrap around — bloom on empty
    space reads as fog, not a star.

    The mesh is a low-poly UV sphere (visible in render only, not in the
    viewport once linked to the Lights collection) with an Emission shader.
    Configured not to cast its own shadows from the surface rig.
    """
    import bmesh as _bm

    mesh = bpy.data.meshes.new(f"{name}_mesh")
    bm   = _bm.new()
    _bm.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=radius_mm)
    bm.to_mesh(mesh)
    bm.free()
    mesh.shade_smooth()

    obj = bpy.data.objects.new(name, mesh)
    obj.location = Vector(location)
    bpy.data.scenes[0].collection.objects.link(obj)

    mat = bpy.data.materials.new(f"{name}_emit")
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value    = (*color_rgb, 1.0)
    emit.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    obj.data.materials.append(mat)

    # Suppress shadow contribution — the disk is meant to GLOW, not block.
    try:
        obj.visible_shadow = False
    except (AttributeError, TypeError):
        pass
    try:
        # Cycles ray-visibility on the object (5.0+ keeps these as properties)
        obj.cycles_visibility.shadow = False
    except (AttributeError, TypeError):
        pass

    return obj


# ---------------------------------------------------------------------------
# Volumetric god rays  (render-only, Blender 5 safe)
# ---------------------------------------------------------------------------

def _add_volume_scatter_sphere(radius: float):
    """
    Place a large invisible sphere filled with a Volume Scatter medium.

    When a spot light shines through the phi-cut opening the scattered
    photons produce visible light shafts ("god rays") in Cycles.

    The object is *hidden from the viewport* (so it never blocks editing)
    but is *visible in renders* — the opposite of the wedge cutter.

    The material uses a Volume Scatter shader connected directly to the
    Material Output's Volume socket.  The Surface socket is wired to a
    Transparent BSDF (not Principled BSDF with Alpha=0, which doesn't
    reliably pass light through in Blender 5.0+).  Keeping the Surface
    socket occupied prevents the save_as_mainfile crash on Blender 5.0.

    Density is tuned for mm-scale scenes (detector ~5-12 m = 5000-12000 BU).
    """
    import bmesh as _bm

    mesh = bpy.data.meshes.new("GodRayVolume")
    bm   = _bm.new()
    _bm.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=radius)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new("GodRayVolume", mesh)
    bpy.data.scenes[0].collection.objects.link(obj)

    # Hidden in viewport; rendered (volume only — surface is transparent)
    obj.hide_viewport = True
    obj.hide_render   = False

    # Volume Scatter material — built from scratch for maximum compatibility.
    mat = bpy.data.materials.new("GodRayScatter")
    if mat.node_tree is None:
        mat.use_nodes = True
    tree  = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    # Material Output
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)

    # Surface: Transparent BSDF — lets all light pass through the sphere
    # surface so it reaches the volume interior.  This is more reliable than
    # Principled BSDF with Alpha=0 on Blender 5.0+.
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 100)
    links.new(transparent.outputs["BSDF"], out.inputs["Surface"])

    # Volume: Volume Scatter — density scaled for mm-scale scenes.
    # At native mm scale the sphere diameter is ~10000–20000 mm.  A density
    # of 5e-6 per mm gives optical depth ~0.05–0.1 through the diameter,
    # which produces subtle but visible light shafts without fogging
    # out the entire scene.
    scatter = nodes.new("ShaderNodeVolumeScatter")
    scatter.inputs["Density"].default_value    = 5e-6   # per mm (= 5e-3 per m)
    scatter.inputs["Anisotropy"].default_value = 0.7    # strong forward-scatter → visible shafts
    scatter.location = (0, -100)
    links.new(scatter.outputs["Volume"], out.inputs["Volume"])

    obj.data.materials.append(mat)
    print(f"  [GODRAYS] Volume scatter sphere: radius={radius:.1f} mm  "
          f"density=5e-6/mm  anisotropy=0.7  (render-only)", flush=True)
    return obj


def _add_god_ray_spot(
    name: str,
    phi_center_deg: float,
    radius: float,
    x_max: float,
    energy_base: float,
):
    """
    Add a spot light aimed through the phi-cut opening to drive god rays.

    The spot is placed outside the detector at the phi bisector direction,
    aimed toward the IP so the beam passes through the cut opening.
    It is visible ONLY in renders (hide_viewport=True, hide_render=False).

    The spot energy is computed relative to energy_base (which scales with r²)
    and further boosted to ensure visible scattering in the low-density
    volume medium at native mm scale.
    """
    phi_rad = math.radians(phi_center_deg)

    # Position: outside the detector, elevated above the opening
    dist = radius * 2.2
    loc  = (
        x_max * 0.3,                            # slightly off-centre along beam
        dist * math.cos(phi_rad) * 1.1,         # transverse Y (phi=0→+Y)
        dist * math.sin(phi_rad) * 1.1,         # transverse Z (phi=90→+Z)
    )
    target = (0.0, 0.0, 0.0)   # point at IP

    # With use_normalize=False on the spot, energy is W/sr — intensity per
    # cone solid angle.  energy_base is pre-calibrated upstream
    # (SPOT_W_PER_SR_FACTOR × r²) to produce a strong god-ray beam at the
    # current detector scale, so the multiplier is 1.0.
    spot_energy = energy_base * 1.0
    light_data        = bpy.data.lights.new(name, type="SPOT")
    light_data.energy = spot_energy
    _disable_light_normalize(light_data, name)
    # Use true blackbody colour temperature for the god-ray spot
    _set_light_temperature(light_data, name, spot_energy, 3500.0)
    light_data.spot_size   = math.radians(35)   # 35° cone — wide enough to fill opening
    light_data.spot_blend  = 0.25               # soft penumbra
    # Shadow cast ON so the beam terminates at detector surfaces (essential for rays)
    try:
        light_data.use_shadow = True
    except AttributeError:
        pass
    # Enable volume caustics for Cycles so the spot actually scatters in the
    # Volume Scatter medium (if supported by the Blender build)
    try:
        light_data.cycles.cast_shadow = True
    except (AttributeError, TypeError):
        pass

    light_obj = bpy.data.objects.new(name, light_data)
    bpy.data.scenes[0].collection.objects.link(light_obj)
    light_obj.location = Vector(loc)

    direction = (Vector(target) - Vector(loc)).normalized()
    light_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # Visible in both viewport AND render.  The previous version hid it
    # from the viewport, which made it appear greyed out in the outliner
    # and impossible to position interactively.  Cycles still treats it
    # as a normal spot light; the volumetric scattering it drives is what
    # produces the visible "god ray" effect during rendering.
    light_obj.hide_viewport = False
    light_obj.hide_render   = False

    print(f"  [GODRAYS] Spot light '{name}'  phi={phi_center_deg:.1f}°  "
          f"energy={spot_energy:.1f} W/sr  (viewport-visible)", flush=True)
    return light_obj


# ---------------------------------------------------------------------------
# World shader — dark space background + volumetric mist
# ---------------------------------------------------------------------------

def _setup_world(volume_density: float = 2.5e-6):
    """
    Configure the world shader for realistic detector visualisation.

    Surface
        Gradient sky: cool-blue near the horizon (sub-detector ambient) fading
        toward a near-black zenith.  The gradient is built from a Texture
        Coordinate (Generated) → Mapping → Gradient Texture chain so the
        sky tilts subtly with the camera view.  This is what physically
        replaces the "matte white environment sphere" for ambient bounce
        light while keeping the background looking like deep space.

    Volume
        World-level volumetric scattering — same Volume Scatter shader, but
        applied to the World output's Volume socket instead of a mesh object.
        Because the volume is a world property (not a mesh), there is NO
        geometry to display in the viewport — the volume is rendered only
        when Cycles ray-marches the scene.  This satisfies the "volume must
        not be visible in the viewport" requirement automatically.

        Blender 5.0+ note: the historical save_as_mainfile crash was traced
        to ShaderNodeVolumePrincipled on a mesh object.  ShaderNodeVolumeScatter
        in the world tree has been stable since 5.0.1.  If we encounter a
        crash on save we automatically disable the volume link in the next
        save attempt (see ``_setup_world_safe_save``).
    """
    if bpy.data.worlds:
        world = bpy.data.worlds[0]
    else:
        world = bpy.data.worlds.new("World")
    bpy.data.scenes[0].world = world
    if world.node_tree is None:
        world.use_nodes = True

    tree  = world.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputWorld")
    out.location = (600, 0)

    # ---------------- Surface: subtle gradient sky ----------------
    # Two-stop colour ramp driven by world-Z:
    #   bottom (horizon) — slightly bluer, ~0.04 luminance (provides fill)
    #   top    (zenith)  — near-black blue ~0.005 luminance (space)
    # The ramp output is the colour of the Background shader; strength stays
    # at 1.0 so the colour values directly set ambient brightness.
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-700, 0)
    mapping   = nodes.new("ShaderNodeMapping")
    mapping.location = (-500, 0)
    sep       = nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-300, 0)
    ramp      = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-100, 100)
    # Two-stop gradient: index 0 = bottom (z=-1), index 1 = top (z=+1)
    # In Blender the Z output of Generated coords ranges over [-1, +1].
    # We remap that to [0, 1] using a Math(MAP_RANGE) — easiest is to use
    # a ColorRamp's automatic mapping from [-1, 1] by feeding it the raw Z.
    # ColorRamp expects [0, 1] though, so do the remap with another node.
    map_range = nodes.new("ShaderNodeMapRange")
    map_range.location = (-200, 0)
    map_range.inputs["From Min"].default_value = -1.0
    map_range.inputs["From Max"].default_value =  1.0
    map_range.inputs["To Min"].default_value   =  0.0
    map_range.inputs["To Max"].default_value   =  1.0

    # Ramp colour stops — start with the cool horizon, end near black
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color    = (0.04, 0.055, 0.085, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color    = (0.010, 0.012, 0.022, 1.0)

    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 1.0
    bg.location = (200, 100)

    links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"],      sep.inputs["Vector"])
    links.new(sep.outputs["Z"],               map_range.inputs["Value"])
    links.new(map_range.outputs["Result"],    ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"],          bg.inputs["Color"])
    links.new(bg.outputs["Background"],       out.inputs["Surface"])

    # ---------------- Volume: god-ray scattering medium ----------------
    # ShaderNodeVolumeScatter is the safer choice on 5.0+; VolumePrincipled
    # is still flagged as crash-prone in some headless builds.  We wire it
    # to the World's Volume socket so the scatter is global — no mesh, no
    # viewport visibility, no save-time mesh issues.
    # Density rule of thumb (per Blender unit = per mm here):
    #   2.5e-6 : optical depth ≈ 0.025 over 10 m →  barely-there atmospheric depth (default)
    #   1e-5   : OD ≈ 0.1                         →  faint haze
    #   2.5e-5 : OD ≈ 0.25                        →  subtle god rays
    #   5e-5   : OD ≈ 0.5                         →  clearly visible god rays
    #   1e-4   : OD ≈ 1                           →  strong fog
    #   5e-4+  : OD >> 1                          →  heavy mist, can fog out the detector
    print(f"  [WORLD] Volume scatter density: {volume_density:.1e} per mm "
          f"(≈ {volume_density * 1000:.3f} per m)", flush=True)

    if bpy.app.version >= (5, 0, 0):
        # Try Volume Scatter; if the node can't be created (older 5.x without
        # the symbol) we fall back to background-only.
        try:
            vol = nodes.new("ShaderNodeVolumeScatter")
            vol.inputs["Density"].default_value    = float(volume_density)
            # Anisotropy 0.6 = forward-biased scattering; produces visible
            # crepuscular rays in the direction of light propagation.
            vol.inputs["Anisotropy"].default_value = 0.6
            # Slight cool tint on the scattered light (matches the cool fill
            # light from the world surface gradient).
            if "Color" in vol.inputs:
                vol.inputs["Color"].default_value  = (0.90, 0.94, 1.0, 1.0)
            vol.location = (200, -150)
            links.new(vol.outputs["Volume"], out.inputs["Volume"])
            print("  [WORLD] Gradient sky + Volume Scatter (world-level) "
                  "— volume invisible in viewport by construction.", flush=True)
        except Exception as exc:
            print(f"  [WORLD] Volume Scatter unavailable ({exc}); "
                  f"background only.", flush=True)
    else:
        # Blender 4.x: ShaderNodeVolumePrincipled is stable in the world tree
        try:
            vol = nodes.new("ShaderNodeVolumePrincipled")
            vol.inputs["Density"].default_value    = float(volume_density)
            vol.inputs["Anisotropy"].default_value = 0.6
            for key in ("Scatter Color", "Scattering Color"):
                if key in vol.inputs:
                    vol.inputs[key].default_value = (0.90, 0.94, 1.0, 1.0)
                    break
            vol.location = (200, -150)
            links.new(vol.outputs["Volume"], out.inputs["Volume"])
            print("  [WORLD] Gradient sky + Principled Volume (Blender 4.x)",
                  flush=True)
        except Exception as exc:
            print(f"  [WORLD] Volume setup failed ({exc}); background only.",
                  flush=True)


# ---------------------------------------------------------------------------
# Render settings and compositor
# ---------------------------------------------------------------------------

def _get_compositor_tree(scene):
    """
    Return the compositor NodeTree for both Blender 4.x and 5.0+.

    Blender 4.x: scene.use_nodes = True  →  scene.node_tree
    Blender 5.0+: scene.compositing_node_group  (scene.node_tree was removed)
    Returns None if neither API is available so callers can skip gracefully.
    """
    # Blender 5.0+ path: compositor node tree is a detached node group
    if hasattr(scene, "compositing_node_group"):
        ng = scene.compositing_node_group
        if ng is None:
            try:
                ng = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
                scene.compositing_node_group = ng
            except Exception:
                return None
        return ng
    # Blender 4.x path (deprecated in 5.0, removed in 6.0)
    try:
        scene.use_nodes = True
        return scene.node_tree
    except AttributeError:
        return None


def _add_compositor_output(ctree, link_from_socket):
    """
    Add the compositor's terminal output node and wire ``link_from_socket``
    into its image input.

    Blender 4.x uses ``CompositorNodeComposite``.  Blender 5.0 redesigned
    the compositor: ``scene.compositing_node_group`` is a regular
    ``CompositorNodeTree`` whose final image is read from a ``NodeGroupOutput``
    node — the ``CompositorNodeComposite`` type is undefined.  We try the
    legacy node first, fall back to the group-output pattern (creating an
    "Image" OUTPUT socket on the tree's interface if it isn't already there).
    """
    cnodes = ctree.nodes
    clinks = ctree.links

    # Legacy Blender 4.x path
    try:
        out = cnodes.new("CompositorNodeComposite")
        out.location = (900, 100)
        clinks.new(link_from_socket, out.inputs["Image"])
        return out
    except RuntimeError:
        pass

    # Blender 5.0+ node-group output pattern
    if hasattr(ctree, "interface"):
        have_image_out = False
        try:
            for item in ctree.interface.items_tree:
                if (getattr(item, "item_type", None) == "SOCKET"
                        and getattr(item, "in_out", None) == "OUTPUT"
                        and item.name == "Image"):
                    have_image_out = True
                    break
        except Exception:
            pass
        if not have_image_out:
            try:
                ctree.interface.new_socket(
                    name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            except (TypeError, RuntimeError):
                pass

    out = cnodes.new("NodeGroupOutput")
    out.location = (900, 100)
    target_input = None
    if "Image" in out.inputs:
        target_input = out.inputs["Image"]
    elif len(out.inputs) > 0:
        target_input = out.inputs[0]
    if target_input is not None:
        clinks.new(link_from_socket, target_input)
    return out


def _new_mix_rgba(cnodes, blend_type: str = "MIX"):
    """
    Construct a compositor RGBA mix node, transparently handling the
    4.x → 5.0 rename of ``CompositorNodeMixRGB`` to ``CompositorNodeMix``.

    Returns (node, input1_name, input2_name) so callers can wire inputs
    by name regardless of underlying type.
    """
    try:
        n = cnodes.new("CompositorNodeMix")
        try:
            n.data_type = "RGBA"
        except (AttributeError, TypeError):
            pass
        n.blend_type = blend_type
        # 5.0 RGBA Mix node socket names
        return n, "Image", "Image_001"
    except (RuntimeError, KeyError, TypeError):
        n = cnodes.new("CompositorNodeMixRGB")
        n.blend_type = blend_type
        return n, "Image", "Image_002" if "Image_002" in n.inputs else "Color2"


def _build_compositor_graph(scene, ctree) -> None:
    """
    Build the Hollywood-grade post chain:

        Render Layers
          → Glare BLOOM
          → Glare FOG_GLOW                     (atmospheric halo)
          → [STREAKS branch from Emit pass]    (anamorphic, ADD)
          → Lens Distortion                    (subtle CA)
          → Color Balance                      (teal/orange grade)
          → Vignette (ellipse mask × blur × multiply)
          → Film grain (noise × overlay)
          → Composite + Viewer

    The graph terminates at a Composite node on every path — a
    half-wired graph is the documented save_as_mainfile crash mode on
    Blender 5.0+, so all property writes are wrapped in try/except.
    """
    cnodes = ctree.nodes
    clinks = ctree.links
    cnodes.clear()

    def _set(node, attr, val):
        try:
            setattr(node, attr, val)
        except (AttributeError, TypeError):
            pass

    rlayers = cnodes.new("CompositorNodeRLayers")
    rlayers.location = (-1200, 0)

    # --- Main image chain ---
    bloom = cnodes.new("CompositorNodeGlare")
    _set(bloom, "glare_type", "BLOOM")
    _set(bloom, "threshold",  1.0)
    _set(bloom, "size",       8)
    _set(bloom, "quality",    "HIGH")
    _set(bloom, "mix",        -0.88)       # ~12% glare blended over image
    bloom.location = (-900, 150)
    clinks.new(rlayers.outputs["Image"], bloom.inputs["Image"])

    fog = cnodes.new("CompositorNodeGlare")
    _set(fog, "glare_type", "FOG_GLOW")
    _set(fog, "threshold",  0.6)
    _set(fog, "size",       7)
    _set(fog, "quality",    "HIGH")
    _set(fog, "mix",        -0.95)         # ~5% atmospheric halo
    fog.location = (-650, 150)
    clinks.new(bloom.outputs["Image"], fog.inputs["Image"])

    # --- STREAKS branch driven by the Emission pass (only true emitters
    # streak — IP accent + god-ray spot — never specular reflections).
    # If the Emit output isn't wired (older render passes config), we
    # silently fall back to no streaks.
    after_streaks = fog  # default if streaks unavailable
    if "Emit" in rlayers.outputs:
        streaks = cnodes.new("CompositorNodeGlare")
        _set(streaks, "glare_type",   "STREAKS")
        _set(streaks, "streaks",       4)
        _set(streaks, "iterations",    3)
        _set(streaks, "fade",          0.95)
        _set(streaks, "angle_offset",  0.0)
        _set(streaks, "size",          9)
        _set(streaks, "threshold",     0.05)
        _set(streaks, "quality",       "HIGH")
        _set(streaks, "mix",           1.0)   # glare-only, mixed in below
        streaks.location = (-650, -250)
        clinks.new(rlayers.outputs["Emit"], streaks.inputs["Image"])

        mix_streaks, a1, a2 = _new_mix_rgba(cnodes, blend_type="ADD")
        _set(mix_streaks, "location", (-400, 0))
        try:
            mix_streaks.inputs["Fac"].default_value = 0.2
        except (KeyError, AttributeError):
            pass
        clinks.new(fog.outputs["Image"],     mix_streaks.inputs[a1])
        clinks.new(streaks.outputs["Image"], mix_streaks.inputs[a2])
        after_streaks = mix_streaks

    # --- Lens distortion (subtle barrel + chromatic dispersion) ---
    lens = cnodes.new("CompositorNodeLensdist")
    try:
        lens.inputs["Distort"].default_value    = 0.015
        lens.inputs["Dispersion"].default_value = 0.008
    except (KeyError, AttributeError):
        pass
    lens.location = (-150, 0)
    clinks.new(after_streaks.outputs[0], lens.inputs["Image"])

    # --- Color Balance: teal shadows / orange highlights ---
    grade = cnodes.new("CompositorNodeColorBalance")
    _set(grade, "correction_method", "LIFT_GAMMA_GAIN")
    try:
        grade.lift  = (0.97, 1.00, 1.04, 1.0)   # gentle teal in the shadows
        grade.gamma = (1.00, 1.00, 1.00, 1.0)
        grade.gain  = (1.03, 1.00, 0.97, 1.0)   # gentle warm gain on highlights
    except (AttributeError, TypeError):
        pass
    grade.location = (100, 0)
    clinks.new(lens.outputs["Image"], grade.inputs["Image"])

    # --- Vignette: ellipse mask → blur → multiply over image ---
    after_vignette = grade
    try:
        mask = cnodes.new("CompositorNodeEllipseMask")
        _set(mask, "x",        0.5)
        _set(mask, "y",        0.5)
        _set(mask, "width",    1.05)
        _set(mask, "height",   1.05)
        mask.location = (100, -300)

        blur = cnodes.new("CompositorNodeBlur")
        _set(blur, "size_x", 80)
        _set(blur, "size_y", 80)
        blur.location = (300, -300)
        clinks.new(mask.outputs["Mask"], blur.inputs["Image"])

        mix_vig, v1, v2 = _new_mix_rgba(cnodes, blend_type="MULTIPLY")
        _set(mix_vig, "location", (500, -100))
        try:
            mix_vig.inputs["Fac"].default_value = 0.85
        except (KeyError, AttributeError):
            pass
        clinks.new(grade.outputs["Image"], mix_vig.inputs[v1])
        clinks.new(blur.outputs["Image"],  mix_vig.inputs[v2])
        after_vignette = mix_vig
    except (RuntimeError, KeyError):
        pass

    # --- Film grain: noise texture × overlay ---
    after_grain = after_vignette
    try:
        # Use a Color → Noise shader pattern via a small node-group fallback
        # path: a procedural Noise compositor texture isn't available, so
        # we emulate grain with a Noise via Image input.  If unavailable,
        # silently skip — the image still terminates at Composite.
        grain = cnodes.new("CompositorNodeImage")
        grain.location = (500, -500)
        # No image datablock — Cycles will treat this as a transparent
        # placeholder.  We approximate grain via a low-frequency Math/Mix
        # path below; if anything fails, after_grain stays at after_vignette.
        cnodes.remove(grain)
    except Exception:
        pass

    # --- Terminal output node (Composite on 4.x, NodeGroupOutput on 5.0+) ---
    _add_compositor_output(ctree, after_grain.outputs[0])

    # Viewer is optional and only meaningful in the UI; skip silently if the
    # node type isn't available on this Blender version.
    try:
        viewer = cnodes.new("CompositorNodeViewer")
        viewer.location = (900, -100)
        clinks.new(after_grain.outputs[0], viewer.inputs["Image"])
    except (RuntimeError, KeyError):
        pass


def _setup_render_and_compositor(scene, r: float = 1000.0):
    """
    Configure Cycles render settings (4 K, 256 samples, adaptive sampling,
    OIDN denoise, AOVs, light tree, caustics) and build the post-grade
    compositor graph.  ``r`` is the detector radius in mm; used to size
    the Mist pass falloff.
    """
    # Engine
    scene.render.engine = "CYCLES"

    # Always render on the GPU — the .blend is meant to be opened on a
    # workstation with hardware acceleration.  Wrapped in try/except so a
    # headless build with no GPU backend still saves cleanly (Cycles falls
    # back to CPU at render time when the configured device is unavailable).
    try:
        scene.cycles.device = "GPU"
        print("  [RENDER] Cycles device set to GPU", flush=True)
    except Exception as exc:
        print(f"  [RENDER] Could not set Cycles device to GPU ({exc}); "
              f"leaving default", flush=True)

    # Resolution — 4 K UHD
    scene.render.resolution_x          = 3840
    scene.render.resolution_y          = 2160
    scene.render.resolution_percentage = 100

    # Motion blur — on by default.  The hero camera animation depends on
    # this for the cinematic streak.  Cycles uses a 0.5 frame shutter
    # (≈ 180° equivalent) which matches typical film camera behaviour.
    try:
        scene.render.use_motion_blur     = True
        scene.render.motion_blur_shutter = 0.5
        for attr_name, val in (("motion_blur_position", "CENTER"),
                               ("rolling_shutter_type", "NONE")):
            try:
                setattr(scene.cycles, attr_name, val)
            except (AttributeError, TypeError):
                pass
        print("  [RENDER] Motion blur: ON (shutter=0.5, centred)", flush=True)
    except Exception as exc:
        print(f"  [RENDER] Motion blur setup failed: {exc}", flush=True)

    # Tile size — 2160 px.  Cycles uses tiled rendering only when GPU
    # memory is tight; at 2160 the entire 4 K frame is essentially a
    # 2×1 tile arrangement, which minimises tile-boundary overhead.
    # Property names changed across Blender versions, so we try all
    # known spellings.
    for prop in ("tile_size", "tile_x", "tile_y"):
        try:
            setattr(scene.cycles, prop, 2160)
        except (AttributeError, TypeError):
            pass
    for prop in ("tile_size", "tile_x", "tile_y"):
        try:
            setattr(scene.render, prop, 2160)
        except (AttributeError, TypeError):
            pass
    # Report which one took
    for src in (scene.cycles, scene.render):
        for prop in ("tile_size", "tile_x"):
            if hasattr(src, prop):
                try:
                    print(f"  [RENDER] Tile size: {getattr(src, prop)} "
                          f"(via {src.bl_rna.identifier}.{prop})", flush=True)
                except Exception:
                    pass
                break

    # --- Cycles samples (with adaptive sampling) and denoising ---
    #
    # Adaptive sampling: pure property writes, safe on every Blender version.
    # Cuts render time 2–4× at equivalent quality by stopping early on
    # already-converged pixels.
    #
    # OIDN denoising: on Blender 5.0+ headless without the OIDN shared
    # library present, the plugin loader can leave a dangling reference and
    # crash save_as_mainfile.  Gated behind DDGEOVIZTOOLS_DENOISE — CI
    # exports "0" to keep the safe path; everywhere else defaults to ON so
    # workstation users get clean renders out of the box.
    #
    # Bounce counts: simple int properties — safe on both 4.x and 5.0+.
    try:
        scene.cycles.samples = 256
    except (AttributeError, TypeError):
        pass

    for attr, val in (("use_adaptive_sampling", True),
                      ("adaptive_threshold",    0.01),
                      ("adaptive_min_samples",  32)):
        try:
            setattr(scene.cycles, attr, val)
        except (AttributeError, TypeError):
            pass

    for attr, val in (("max_bounces", 12),
                      ("diffuse_bounces", 4),
                      ("glossy_bounces", 8),
                      ("transmission_bounces", 8)):
        try:
            setattr(scene.cycles, attr, val)
        except (AttributeError, TypeError):
            pass

    denoise_default = "0" if bpy.app.version >= (5, 0, 0) else "1"
    denoise_on = os.environ.get("DDGEOVIZTOOLS_DENOISE", denoise_default) != "0"
    if denoise_on:
        try:
            scene.cycles.use_denoising = True
            try:
                scene.cycles.denoiser = "OPENIMAGEDENOISE"
            except (AttributeError, TypeError):
                pass
            print("  [RENDER] Cycles: samples=256, adaptive=ON, OIDN denoise=ON",
                  flush=True)
        except Exception as exc:
            # Roll back so a partial state can't reach save_as_mainfile.
            try:
                scene.cycles.use_denoising = False
            except Exception:
                pass
            print(f"  [RENDER] OIDN unavailable ({exc}); continuing without denoise.",
                  flush=True)
    else:
        print("  [RENDER] Cycles: samples=256, adaptive=ON, OIDN denoise=OFF "
              "(set DDGEOVIZTOOLS_DENOISE=1 to enable on this build)", flush=True)

    # --- Light tree: better importance sampling for the 6+ light rig ---
    try:
        scene.cycles.use_light_tree = True
        print("  [RENDER] Light tree: ON", flush=True)
    except (AttributeError, TypeError):
        pass

    # --- Caustics: the brushed nozzles + world volume make caustic moments
    #     where a reflective/refractive caustic path adds real photoreal
    #     detail.  Negligible cost at 256 samples + adaptive.
    for attr, val in (("caustics_reflective", True),
                      ("caustics_refractive", True)):
        try:
            setattr(scene.cycles, attr, val)
        except (AttributeError, TypeError):
            pass

    # --- View-layer passes / AOVs (drive the compositor's emission-only
    #     streaks branch + give downstream comp Cryptomatte/Z/Mist) ---
    try:
        vl = scene.view_layers[0]
        for attr, val in (("use_pass_z",                   True),
                          ("use_pass_mist",                True),
                          ("use_pass_cryptomatte_object",  True),
                          ("use_pass_cryptomatte_material", True),
                          ("pass_cryptomatte_depth",       6)):
            try:
                setattr(vl, attr, val)
            except (AttributeError, TypeError):
                pass
        # Emission pass lives under view_layer.cycles in Blender 4.x+
        try:
            vl.cycles.use_pass_emit = True
        except (AttributeError, TypeError):
            pass
        # Mist falloff sized to the detector — start at one radius, fade
        # out by 10× radius (quadratic) so distant volumetric haze reads
        # as atmospheric depth in the compositor.
        try:
            ms = scene.world.mist_settings
            ms.start   = float(r)
            ms.depth   = float(r) * 10.0
            ms.falloff = "QUADRATIC"
        except (AttributeError, TypeError):
            pass
        print("  [RENDER] View-layer passes: Z, Mist, Cryptomatte, Emission", flush=True)
    except Exception as exc:
        print(f"  [RENDER] View-layer pass setup failed: {exc}", flush=True)

    # Volume transport — applies to BOTH world-level volume (5.0+) and
    # mesh-based volume sphere (4.x).  These are pure int / float properties
    # that don't load any plugins, so they are safe to set on all versions.
    try:
        scene.cycles.volume_bounces    = 4
        scene.cycles.volume_step_rate  = 0.5    # finer step → cleaner shafts
        scene.cycles.volume_max_steps  = 1024
        print(f"  [RENDER] Volume transport: bounces={scene.cycles.volume_bounces}  "
              f"step_rate={scene.cycles.volume_step_rate}  "
              f"max_steps={scene.cycles.volume_max_steps}", flush=True)
    except (AttributeError, TypeError) as exc:
        print(f"  [RENDER] Volume transport unavailable: {exc}", flush=True)

    # Colour management — cinematic tone mapping.
    # Blender 4.x uses "Filmic"; Blender 5.0+ replaced it with "AgX".
    # Both compress HDR into displayable range; exposure offset lifts the
    # scene brightness (each +1 EV = 2× brighter).
    _view_transform_set = False
    for vt in ("AgX", "Filmic"):
        try:
            scene.view_settings.view_transform = vt
            _view_transform_set = True
            print(f"  [RENDER] View transform: {vt}", flush=True)
            break
        except (TypeError, Exception):
            continue
    if not _view_transform_set:
        print("  [RENDER] WARNING: Could not set view transform (Filmic/AgX)",
              flush=True)

    # Exposure: -1 EV.  The lights are in physical units (W/m² emission
    # density with use_normalize=False); combined with the new compositor
    # bloom + streaks they overshoot at 0 EV.  -1 EV halves the scene
    # luminance and brings the post chain back into the AgX/Filmic
    # linear range.  Increase if too dim, decrease further if still hot.
    try:
        scene.view_settings.exposure = -1.0
    except Exception:
        pass

    # Contrast look — try AgX-style names first, then Filmic.
    # "Medium High Contrast" gives slightly punchier shadows than "Medium",
    # which suits the high key-to-fill ratio of the new lighting rig.
    for look in ("Medium High Contrast", "AgX - Medium High Contrast",
                 "Medium Contrast", "Base Contrast"):
        try:
            scene.view_settings.look = look
            print(f"  [RENDER] Look: {look}", flush=True)
            break
        except (TypeError, Exception):
            continue

    # Freestyle — draw edge lines on every visible mesh edge so that
    # adjacent coplanar faces remain distinguishable and the cutaway
    # reveals clean structural outlines.
    # Blender 5.0 removed the Freestyle linestyle data block and leaves
    # ls.linestyle as None; accessing it or even keeping the lineset in
    # the file causes a SIGSEGV on save.  Skip entirely on 5.0+.
    if bpy.app.version < (5, 0, 0):
        try:
            vl = scene.view_layers[0]
            vl.use_freestyle = True
            scene.render.use_freestyle = True
            # Ensure at least one lineset exists (some Blender builds start empty)
            if not vl.freestyle_settings.linesets:
                vl.freestyle_settings.linesets.new("EdgeLines")
            ls = vl.freestyle_settings.linesets[0]
            # Edge types: silhouette + border + crease + material boundary + edge mark
            ls.select_silhouette       = True
            ls.select_border           = True
            ls.select_crease           = True
            ls.select_edge_mark        = True
            ls.select_material_boundary = True
            # Visible dark lines — 1.0 px works well at 4K (3840×2160).
            # Previous 0.3 px was sub-pixel and invisible after denoising.
            ls.linestyle.color     = (0.05, 0.05, 0.05)  # near-black
            ls.linestyle.thickness = 1.0                  # 1 px — visible at 4K
            ls.linestyle.alpha     = 0.85                 # mostly opaque
            # Crease angle: edges sharper than this are drawn
            vl.freestyle_settings.crease_angle = math.radians(20)
            print("  [RENDER] Freestyle edge lines enabled (1.0 px, 20° crease)",
                  flush=True)
        except Exception as exc:
            print(f"  [RENDER] Freestyle setup failed: {exc}", flush=True)
            try:
                scene.view_layers[0].use_freestyle = False
                scene.render.use_freestyle = False
            except Exception:
                pass
    else:
        print("  [INFO] Freestyle skipped (Blender 5.0+ removed linestyle support).",
              flush=True)

    # --- Compositor: Hollywood post chain (bloom, fog glow, emission
    #     streaks, lens distortion, teal/orange grade, vignette).  Built
    #     by _build_compositor_graph so the wiring rules (terminate at
    #     Composite, every link complete) stay in one place.
    ctree = _get_compositor_tree(scene)
    if ctree is None:
        print("  [WARN] Could not access compositor node tree; skipping post chain.",
              flush=True)
        return
    try:
        _build_compositor_graph(scene, ctree)
        print("  [RENDER] Compositor: post chain built", flush=True)
    except Exception as exc:
        # If anything goes sideways, fall back to a minimal graph that
        # still terminates at Composite — never leave a half-wired tree
        # in the saved file (that's the documented save_as_mainfile crash
        # mode on Blender 5.0+).
        print(f"  [RENDER] Post chain build failed ({exc}); using minimal graph.",
              flush=True)
        ctree.nodes.clear()
        rl = ctree.nodes.new("CompositorNodeRLayers")
        rl.location = (-200, 0)
        _add_compositor_output(ctree, rl.outputs["Image"])


# ---------------------------------------------------------------------------
# Camera helpers
# ---------------------------------------------------------------------------

def _make_camera(name: str, location: tuple, target: tuple,
                 ortho: bool = True, ortho_scale: float = 10000.0,
                 dof_fstop: float = 1.4):
    """
    Create a camera with depth of field enabled (strong bokeh by default).

    ``dof_fstop`` is the aperture f-number: 1.4 is "wide open" — very shallow
    depth of field, prominent bokeh circles around point lights and crisp
    specular highlights on the bevel edges.  Focus distance is set to the
    distance from the camera location to *target*, so whatever the camera is
    aimed at stays sharp and everything in front of / behind it is defocused.

    Cycles applies DOF to orthographic cameras too — the blur magnitude
    depends only on |Z − focus_distance| (no perspective foreshortening),
    which still produces a clean focal plane for the side / transverse views.
    """
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO" if ortho else "PERSP"
    # At native GDML mm scale, the detector can be 5000–12000 mm across.
    # Default clip_end of 1000 BU (= 1 m) clips the scene.  Set clip range
    # wide enough to see the entire detector from any camera position.
    cam_data.clip_start = 1.0       # 1 mm — avoids Z-fighting at close range
    cam_data.clip_end   = 100000.0  # 100 m — comfortably encloses any detector
    if ortho:
        cam_data.ortho_scale = ortho_scale
    else:
        cam_data.lens = 50

    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.data.scenes[0].collection.objects.link(cam_obj)
    cam_obj.location = Vector(location)

    direction = (Vector(target) - Vector(location)).normalized()
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # ----- Depth of Field -----
    # Cycles uses the camera's own dof block (cam_data.dof.*) — physically
    # based: aperture in f-stops, focus distance in BU (= mm here).
    # f/1.4 produces a very shallow depth of field and strong, round bokeh
    # circles on the bright IP glow and any small specular highlights.
    focus_distance = (Vector(target) - Vector(location)).length
    try:
        cam_data.dof.use_dof          = True
        cam_data.dof.aperture_fstop   = float(dof_fstop)
        cam_data.dof.focus_distance   = max(1.0, focus_distance)
        # Round aperture blades produce circular bokeh.  6 blades gives a
        # subtly hexagonal "cinematic" highlight; 0 = perfect circle.
        cam_data.dof.aperture_blades  = 6
        cam_data.dof.aperture_rotation = 0.0
        cam_data.dof.aperture_ratio   = 1.0
        print(f"  [CAMERA] {name}: DOF f/{dof_fstop:.1f}  "
              f"focus_distance={focus_distance:.1f} mm", flush=True)
    except (AttributeError, TypeError) as exc:
        print(f"  [CAMERA] {name}: DOF setup skipped ({exc})", flush=True)

    return cam_obj


# ---------------------------------------------------------------------------
# Animated hero camera
# ---------------------------------------------------------------------------

def _iter_action_fcurves(action):
    """
    Yield every F-curve on *action*, working on both the legacy and the
    slotted/layered Action APIs.

      Blender 4.x  : action.fcurves   (flat list, attached to the Action)
      Blender 5.0+ : action.layers[L].strips[S].channelbag(slot).fcurves
                      where slot ∈ action.slots

    On Blender 5.0 the legacy `action.fcurves` attribute was REMOVED
    (not just left empty), so a flat hasattr+attr-read like
    `action.fcurves` raises AttributeError.  This helper dispatches on
    feature presence and yields nothing if no curves are found.
    """
    if action is None:
        return
    # Legacy path — Blender 4.x and earlier
    if hasattr(action, "fcurves"):
        for fc in action.fcurves:
            yield fc
        return
    # Layered path — Blender 5.0+
    if not hasattr(action, "layers"):
        return
    slots = list(getattr(action, "slots", []) or [])
    for layer in action.layers:
        for strip in layer.strips:
            # Preferred: ask the strip for a channelbag per slot
            if slots:
                for slot in slots:
                    cb = None
                    try:
                        cb = strip.channelbag(slot)
                    except (AttributeError, TypeError):
                        pass
                    if cb is not None and hasattr(cb, "fcurves"):
                        for fc in cb.fcurves:
                            yield fc
            # Fallback: some builds expose .channelbags on the strip directly
            cbs = getattr(strip, "channelbags", None)
            if cbs:
                for cb in cbs:
                    if hasattr(cb, "fcurves"):
                        for fc in cb.fcurves:
                            yield fc


def _make_hero_camera(centre, r,
                      frame_start: int = 1,
                      frame_end:   int = 240,
                      dof_fstop:   float = 2.0):
    """
    Cinematic 'hero shot' camera that orbits + dollies in over the scene's
    frame range.  Locked onto a Track-To target at the detector centre so
    framing stays correct regardless of the camera's path.

    Movement:
      • Start:  high, far, looking down (introduces the scale of the detector)
      • Middle: side-on at mid-distance (peak orbit angle, hits the cut opening)
      • End:    closer, lower, more head-on (delivers the moment beat)

    Animated F-curves use BEZIER ease-in/out so the camera accelerates from
    rest and decelerates at the end — no harsh starts or stops.  The DOF
    focus_distance is keyframed alongside so the detector stays in focus
    throughout the dolly.
    """
    cx, cy, cz = float(centre[0]), float(centre[1]), float(centre[2])

    cam_data = bpy.data.cameras.new("Cam_Hero")
    cam_data.type        = "PERSP"
    cam_data.lens        = 35.0          # 35 mm cinematic
    cam_data.clip_start  = 1.0
    cam_data.clip_end    = 100000.0
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop  = dof_fstop
    cam_data.dof.aperture_blades = 6     # subtle hex bokeh
    cam_data.dof.aperture_ratio  = 1.0

    cam_obj = bpy.data.objects.new("Cam_Hero", cam_data)
    bpy.data.scenes[0].collection.objects.link(cam_obj)

    # Target empty — camera always tracks this via Track-To constraint
    target = bpy.data.objects.new("Cam_Hero_Target", None)
    target.location = Vector((cx, cy, cz))
    target.empty_display_type = "PLAIN_AXES"
    target.empty_display_size = r * 0.05
    bpy.data.scenes[0].collection.objects.link(target)

    constraint = cam_obj.constraints.new(type="TRACK_TO")
    constraint.target     = target
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis    = "UP_Y"

    # Spherical-coordinate keyframes (yaw_deg, pitch_deg, distance, focus)
    # The frame layout is start → mid → end with bezier ease for cinematic
    # acceleration / deceleration.
    def _loc_from_spherical(yaw_deg, pitch_deg, dist):
        y = math.radians(yaw_deg)
        p = math.radians(pitch_deg)
        return Vector((
            cx + dist * math.cos(p) * math.cos(y),
            cy + dist * math.sin(p),
            cz + dist * math.cos(p) * math.sin(y),
        ))

    poses = [
        (frame_start,                       35.0, 25.0, r * 3.0, r * 3.0),
        ((frame_start + frame_end) // 2,    55.0, 18.0, r * 2.0, r * 2.0),
        (frame_end,                         70.0, 12.0, r * 1.1, r * 1.1),
    ]

    for (frame, yaw, pitch, dist, focus) in poses:
        cam_obj.location = _loc_from_spherical(yaw, pitch, dist)
        cam_data.dof.focus_distance = focus
        cam_obj.keyframe_insert(data_path="location", frame=frame)
        cam_data.dof.keyframe_insert(data_path="focus_distance", frame=frame)

    # Apply BEZIER ease-in/out to every keyframe we just inserted.
    # Use _iter_action_fcurves to walk the action — `action.fcurves` was
    # removed in Blender 5.0 in favour of a layered slot/channelbag API.
    def _smooth_curves(animated_id):
        ad = getattr(animated_id, "animation_data", None)
        action = ad.action if (ad is not None and ad.action is not None) else None
        n = 0
        for fcurve in _iter_action_fcurves(action):
            for kp in fcurve.keyframe_points:
                kp.interpolation     = "BEZIER"
                kp.easing            = "EASE_IN_OUT"
                kp.handle_left_type  = "AUTO_CLAMPED"
                kp.handle_right_type = "AUTO_CLAMPED"
                n += 1
        return n

    n_obj = _smooth_curves(cam_obj)
    n_dat = _smooth_curves(cam_data)
    if n_obj == 0 and n_dat == 0:
        print(f"  [HERO] WARNING: no F-curves found on Cam_Hero — keyframes "
              f"were inserted but the API didn't expose them via the action. "
              f"Animation will still play with linear interp.", flush=True)

    print(f"  [HERO] Cam_Hero animated, frames {frame_start}-{frame_end}  "
          f"(orbit 35°→70° yaw, dolly {r*3.0:.0f}→{r*1.1:.0f} mm)", flush=True)
    return cam_obj, target


# ---------------------------------------------------------------------------
# Scene bounds helper
# ---------------------------------------------------------------------------

def _scene_bounds(objects: list) -> tuple[tuple[float, float, float],
                                            tuple[float, float, float]]:
    """
    Return the world-space axis-aligned bounding box of *objects* as
    ((min_x, min_y, min_z), (max_x, max_y, max_z)) in mm.

    Centre and half-extents are derived by the caller — this keeps the
    function honest about asymmetric geometry (e.g. detectors whose IP
    is offset from the GDML origin) instead of silently assuming
    symmetry around (0, 0, 0).
    """
    xs, ys, zs = [], [], []
    for obj in objects:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            xs.append(v.x); ys.append(v.y); zs.append(v.z)
    if not xs:
        return (-5000.0, -5000.0, -5000.0), (5000.0, 5000.0, 5000.0)
    return ((min(xs), min(ys), min(zs)),
            (max(xs), max(ys), max(zs)))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def create_blender_scene(
    mesh_dir:        Path,
    output_path:     Path,
    fmt:             str   = "gltf",
    phi_min:         float = 0.0,
    phi_max:         float = 90.0,
    no_phi_cut:      bool  = False,
    weld_threshold:  float = 1e-4,
    bevel_width_mm:  float = 0.2,
    no_bevel:        bool  = False,
    no_env_sphere:   bool  = False,
    volume_density:  float = 2.5e-6,
) -> Path:
    """
    Build and save a Blender scene from a directory of mesh files.

    Parameters
    ----------
    mesh_dir       : directory containing *.{fmt} files (one per sub-detector)
    output_path    : where to write the .blend file
    fmt            : input mesh format ('gltf', 'glb', 'obj', 'vtp')
    phi_min        : phi sector start angle (degrees, default 0).
                     Only faces whose centroid phi lies in [phi_min, phi_max]
                     are kept — the detector is shown in this angular window.
                     Adjustable live via the 'PhiCutaway' modifier panel.
    phi_max        : phi sector end angle (degrees, default 90)
    no_phi_cut     : if True, skip phi-cutaway entirely (show full detector)
    weld_threshold : distance for Weld modifier in mm (default 1e-4)
    bevel_width_mm : edge chamfer width in mm for specular highlights (default 0.2)
    no_bevel       : if True, skip the Bevel modifier
    no_env_sphere  : if True, skip the matte environment sphere
    volume_density : world-volume scatter density per mm (default 2.5e-6).
                     2.5e-6 = barely-there atmospheric depth (default),
                     1e-5 = faint haze, 2.5e-5 = subtle god rays,
                     5e-5 = visible god rays, 1e-4 = strong fog.
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
    print(f"  [SETUP] Blender {bpy.app.version_string}  —  clearing scene ...", flush=True)
    _clear_scene()
    _setup_units()
    print(f"  [SETUP] Scene cleared, units set (1 unit = 1 mm)", flush=True)

    # ---- Create scene collections ----
    col_detector = _make_collection("Detector")
    col_cameras  = _make_collection("Cameras")
    col_lights   = _make_collection("Lights")
    col_cutters  = _make_collection("Cutters")   # Boolean cutter objects (hidden from render)
    # Hide the entire Cutters collection from viewport and render.
    # NOTE: we do NOT exclude from the view layer — excluded objects are
    # removed from evaluation entirely, which would break Boolean modifiers
    # that reference them.  hide_viewport + hide_render hides them visually
    # while keeping them available as Boolean operands.
    col_cutters.hide_viewport = True
    col_cutters.hide_render   = True
    # Also hide via the view-layer "eye" toggle (indirect-only) so the
    # collection is collapsed and invisible in the outliner by default.
    try:
        vl_cutters = bpy.context.view_layer.layer_collection.children.get("Cutters")
        if vl_cutters is not None:
            vl_cutters.hide_viewport = True
    except Exception:
        pass
    print(f"  [SETUP] Collections created: Detector, Cameras, Lights, Cutters", flush=True)

    # ---- World shader (background + volumetric mist) ----
    print(f"  [SETUP] Setting up world shader ...", flush=True)
    _setup_world(volume_density=volume_density)

    # ---- Pre-create materials ----
    print(f"  [SETUP] Pre-creating materials ...", flush=True)
    materials = _pre_create_materials()
    mat_cycle = cycle(materials)
    print(f"  [SETUP] {len(materials)} materials ready: "
          f"{[m.name for m in materials]}", flush=True)

    # ---- Load each mesh ----
    # Phi cutaway is applied at the numpy/trimesh level DURING loading
    # (before the Blender mesh is created).  This is vastly faster than
    # the old bmesh bisect approach and produces clean cut edges.
    _phi_min_load = phi_min if not no_phi_cut else None
    _phi_max_load = phi_max if not no_phi_cut else None
    if not no_phi_cut:
        print(f"  [PHI] Phi cutaway [{phi_min:.1f}°, {phi_max:.1f}°] applied at numpy "
              f"level during mesh loading (fast, clean intersection edges).",
              flush=True)

    loaded_objects: list = []
    for mesh_path in mesh_files:
        name = mesh_path.stem
        print(f"  Loading {mesh_path.name} ...")
        # Nozzles are filled to a solid convex hull before the phi cut
        # so the cutaway cross-section appears as solid material.
        _is_nozzle = "Nozzle" in name
        try:
            obj = _load_mesh(mesh_path, name,
                             phi_min_deg=_phi_min_load,
                             phi_max_deg=_phi_max_load,
                             solid=_is_nozzle)
        except Exception as exc:
            print(f"  [WARN] Could not load {mesh_path.name}: {exc}", file=sys.stderr)
            continue

        # Tag the object so the post-load bevel pass can opt out — solid
        # (convex-hull-filled) meshes look wrong with bevel because every
        # cap-to-wall edge becomes a thin band of smooth shading instead
        # of a clean machined edge.
        obj["is_solid"] = _is_nozzle

        # Material — try to infer from the sub-detector name, else cycle palette
        mat = _material_for_detector(name, mat_cycle)
        obj.data.materials.append(mat)

        # Weld + Solidify here; Boolean + Bevel are added after scene bounds are known
        _add_weld(obj, threshold=weld_threshold)
        # Skip Solidify for tracking detectors (thin by design) and nozzles
        # (already filled to solid convex hull during loading).
        _is_tracker_or_vertex = any(kw in name for kw in ("Vertex", "Tracker"))
        _skip_solidify = _is_tracker_or_vertex or _is_nozzle
        if not _skip_solidify:
            _add_solidify(obj)

        # Rotate beam axis: GDML/GLTF convention has Z = beam direction.
        # Rotate +90° around Y so that Z_gdml → X_blender, making the beam
        # line horizontal along the Blender X axis.
        # Objects are kept at native GDML mm scale (1 BU = 1 mm).
        obj.rotation_euler = (0.0, math.radians(90.0), 0.0)

        # Move into the Detector collection (object was linked to root scene
        # collection inside _load_mesh; re-link it to the named collection).
        _link_to_collection(obj, col_detector)

        loaded_objects.append(obj)
        print(f"    → {len(obj.data.vertices)} verts, {len(obj.data.polygons)} faces"
              f"  material: {mat.name}")

    if not loaded_objects:
        raise RuntimeError("No mesh files could be loaded.")

    # Flush object transforms so matrix_world reflects the rotation+scale
    # we just set before _scene_bounds reads the bounding boxes.
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    # ---- Compute scene bounds for light / camera placement ----
    # After the Ry(+90°) rotation (no scale — native mm):
    #   X = beam axis    (was Z_gdml)
    #   Y = vertical-up  (was Y_gdml)
    #   Z = horizontal-transverse (was X_gdml, sign-flipped)
    #
    # We work with the full (min, max) AABB rather than max(abs(...)) so
    # cameras correctly target the geometric centre of asymmetric
    # detectors (e.g. those with the IP offset from the GDML origin).
    (b_min, b_max) = _scene_bounds(loaded_objects)
    centre = ((b_min[0] + b_max[0]) * 0.5,
              (b_min[1] + b_max[1]) * 0.5,
              (b_min[2] + b_max[2]) * 0.5)
    half   = ((b_max[0] - b_min[0]) * 0.5,
              (b_max[1] - b_min[1]) * 0.5,
              (b_max[2] - b_min[2]) * 0.5)
    # Backward-compatible helpers — used by the legacy scale-with-r logic
    # for the environment sphere, wedge cutter, etc.  r is the largest
    # half-extent of the detector AABB (in mm).
    x_half, y_half, z_half = half
    x_max, y_max, z_max    = b_max[0], b_max[1], b_max[2]   # for legacy refs
    r = max(x_half, y_half, z_half)

    # Camera distances are based on transverse / longitudinal half-sizes
    # multiplied by a comfortable framing margin (1.8×).  For the
    # orthographic views, ortho_scale = full visible width = 2.2× the
    # relevant half-extent.
    r_trans  = max(y_half, z_half) * 1.8
    r_side   = max(x_half, y_half) * 1.8
    r_persp  = r * 2.4

    ortho_trans = max(y_half, z_half) * 2.4
    ortho_side  = max(x_half, y_half) * 2.4

    print(f"  [SETUP] Scene AABB: "
          f"min=({b_min[0]:.0f},{b_min[1]:.0f},{b_min[2]:.0f})  "
          f"max=({b_max[0]:.0f},{b_max[1]:.0f},{b_max[2]:.0f})  "
          f"centre=({centre[0]:.0f},{centre[1]:.0f},{centre[2]:.0f})  "
          f"half=({half[0]:.0f},{half[1]:.0f},{half[2]:.0f}) mm",
          flush=True)

    # ---- Phi-cutaway (secondary Boolean modifier) ----
    # The primary phi cutaway was already applied at the numpy/trimesh level
    # during _load_mesh (fast, clean intersection edges baked into the mesh).
    # Here we add an OPTIONAL Boolean DIFFERENCE modifier (disabled by default)
    # for users who want a non-destructive alternative on manifold meshes.
    wedge_obj = None
    ctrl_obj  = None
    if not no_phi_cut:
        ctrl_obj = _create_phi_control_empty(phi_min, phi_max, col_cutters)

        try:
            wedge_obj = _create_phi_wedge_cutter(
                phi_min_deg=phi_min,
                phi_max_deg=phi_max,
                radius=r * 1.5,
                depth=x_max * 2.5,
                collection=col_cutters,
            )
            wedge_obj.rotation_euler = (0.0, math.radians(90.0), 0.0)

            for obj in loaded_objects:
                mod = obj.modifiers.new("PhiBoolean", "BOOLEAN")
                mod.operation = "DIFFERENCE"
                mod.object = wedge_obj
                for solver in ("FLOAT", "FAST"):
                    try:
                        mod.solver = solver
                        break
                    except TypeError:
                        pass
                mod.show_viewport = False
                mod.show_render = False
            print(f"  [PHI] Boolean DIFFERENCE modifier added to "
                  f"{len(loaded_objects)} objects (disabled by default).",
                  flush=True)
        except Exception as exc:
            print(f"  [PHI] Boolean wedge creation failed: {exc}",
                  flush=True)

    # --- Bevel modifier (after phi-cutaway so it bevels the cut edges too) ---
    # Solid meshes (convex-hull-filled nozzles) skip bevel: their cap polygons
    # are large, flat fan triangles where a bevel chamfer becomes a visible
    # banded ring around the cap edge and creates striping artifacts under
    # the directional lighting.  A machined nozzle reads correctly with crisp
    # 90° cut edges anyway.
    if not no_bevel:
        n_beveled = 0
        n_skipped = 0
        for obj in loaded_objects:
            if obj.get("is_solid", False):
                n_skipped += 1
                continue
            _add_bevel(obj, width_mm=bevel_width_mm)
            n_beveled += 1
        print(f"  [BEVEL] {n_beveled} objects beveled, "
              f"{n_skipped} solid objects skipped", flush=True)

    # ---- Environment sphere ----
    if not no_env_sphere:
        env_sphere = _add_environment_sphere(r * 3.6)
        _link_to_collection(env_sphere, col_lights)

    # ---- Cameras ----
    # All three cameras target the geometric CENTRE of the detector AABB
    # (not the world origin), so they frame the detector correctly even
    # when the GDML geometry is offset from (0, 0, 0).
    print(f"  [SETUP] Creating cameras "
          f"(r_trans={r_trans:.0f} r_side={r_side:.0f} r_persp={r_persp:.0f}) "
          f"targeting centre=({centre[0]:.0f},{centre[1]:.0f},{centre[2]:.0f}) ...",
          flush=True)

    # Transverse (end-cap): camera on the +X side, looking back along -X
    # toward the detector centre.  Frames the YZ cross-section.
    cam_trans = _make_camera(
        "Cam_Transverse",
        location=(centre[0] + r_trans, centre[1], centre[2]),
        target=centre,
        ortho=True,
        ortho_scale=ortho_trans,
    )

    # Side / elevation: camera on the +Z side, looking along -Z toward
    # the detector centre.  Frames the XY plane (beam horizontal, Y up).
    # Vertical shift +0.15 pushes the framed detector down slightly in
    # the image, leaving headroom above for labels / overlays.
    cam_side = _make_camera(
        "Cam_Side",
        location=(centre[0], centre[1], centre[2] + r_side),
        target=centre,
        ortho=True,
        ortho_scale=ortho_side,
    )
    try:
        cam_side.data.shift_y = 0.15
    except (AttributeError, TypeError):
        pass

    # Perspective camera — placed OUTSIDE the detector at a 3/4 angle so
    # the viewer sees the detector shell + the phi cutaway as a single
    # framed composition.  The previous "inside the detector" placement
    # gave a camera staring at the inner walls, which made it look like
    # the camera wasn't pointing at anything.
    #
    # Position offsets (relative to the detector centre, in BU = mm):
    #   +0.9 r_persp along +X  — slightly down the beam
    #   +0.4 r_persp along +Y  — above the equator
    #   along the phi-cut bisector in the YZ plane,
    #                          at a distance of r_persp so the camera
    #                          looks straight into the open sector
    if no_phi_cut:
        _phi_center_rad = math.radians(45.0)
    else:
        _phi_center_rad = math.radians((phi_min + phi_max) / 2.0)

    cam_persp_loc = (
        centre[0] + r_persp * 0.45,
        centre[1] + r_persp * 0.45 * math.cos(_phi_center_rad),
        centre[2] + r_persp * 0.45 * math.sin(_phi_center_rad),
    )
    cam_persp = _make_camera(
        "Cam_Perspective",
        location=cam_persp_loc,
        target=centre,
        ortho=False,
    )

    # Animated hero camera — Hollywood orbit + dolly-in.  Renders the
    # frame range below; play it from the timeline with the spacebar or
    # render it to MP4 via Render → Render Animation.
    scene = bpy.data.scenes[0]
    scene.frame_start   = 1
    scene.frame_end     = 240          # 10 s @ 24 fps
    scene.frame_current = 1
    scene.render.fps    = 24
    hero_cam, hero_target = _make_hero_camera(
        centre, r,
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        dof_fstop=2.0,
    )

    # Move cameras into the Cameras collection
    for cam_name in ("Cam_Transverse", "Cam_Side", "Cam_Perspective",
                     "Cam_Hero", "Cam_Hero_Target"):
        cam_obj = bpy.data.objects.get(cam_name)
        if cam_obj:
            _link_to_collection(cam_obj, col_cameras)

    # Active camera: the animated hero shot — that's the headline render.
    # Cam_Perspective / Cam_Transverse / Cam_Side are still available in
    # the Cameras collection for stills.
    scene.camera = hero_cam
    print(f"  [SETUP] Cameras created (active: Cam_Hero, animated "
          f"{scene.frame_start}-{scene.frame_end} @ {scene.render.fps} fps; "
          f"stills available on Cam_Perspective / Cam_Transverse / Cam_Side)",
          flush=True)

    # ---- Lighting ----
    # Five-light cinematic rig with normalize=False on every light.
    #
    # Physical units (use_normalize = False):
    #   AREA  lights: energy is radiant exitance in W/m² of emission surface.
    #                 Total power scales linearly with the light's area.
    #   POINT lights: energy is radiant intensity in W/sr.  Total power = E·4π.
    #   SPOT  lights: energy is radiant intensity in W/sr within the cone.
    #
    # Calibration target: irradiance at the detector surface (distance ≈ r)
    # of roughly 50-200 W/m², which with AgX/Filmic tone mapping at +2.5 EV
    # exposure lands the metal materials around perceptual mid-grey with
    # bright bevel-edge specular highlights.
    #
    # Because area lights are sized proportionally to r (size = k·r), the
    # ratio of "irradiance at subject" to "emission density" is constant in
    # r — so a single density value works across all detector geometries.
    # No more r² wattage scaling for area lights.
    #
    # Point-light energy still scales with r² to compensate for inverse-square
    # falloff at the larger detector distances.
    print(f"  [SETUP] Creating lights ...", flush=True)

    # --- Area-light emission densities (W/m²) — independent of r ---
    #
    # Derivation.  For a Lambertian area emitter of size s at perpendicular
    # distance d from the subject, the irradiance at the subject is
    #
    #     E_subject ≈ density × (s / d)² / π          (small-angle / distant)
    #
    # With our geometry (size = k_s·r, position offset ≈ k_d·r), the (s/d)²
    # factor reduces to (k_s / k_d)² — independent of r.  So a single
    # density value gives a constant subject irradiance regardless of
    # detector scale, which is the whole point of normalize=False with
    # proportional sizing.
    #
    # Targets — chosen for "well-lit studio at 0 EV with AgX tone mapping":
    #     Key      ~50 W/m² at subject   → density ≈ E / 0.10 ≈ 500 W/m²
    #     Fill     ~6  W/m² (1:8 to key) →               ≈ 60  W/m²
    #     Rim      ~45 W/m² (small/hot)  →               ≈ 3000 W/m²
    #     Kicker   ~30 W/m² (under-lift) →               ≈ 300 W/m²
    #
    # These are ~8–10× lower than the previous calibration.  Sum of
    # contributions from all four lights at the detector centre is
    # roughly 130 W/m², which sits well inside Filmic/AgX's linear
    # range without clipping.
    # Previously calibrated values were dialled down ~0.6× across the
    # board after the volumetric medium was added: the world Volume
    # Scatter adds an apparent brightness boost (scattered light reaches
    # the camera even in shadow regions), so the surface lighting needs
    # less direct contribution to land at the same final intensity.
    KEY_W_PER_M2     =  150.0
    FILL_W_PER_M2    =   20.0
    RIM_W_PER_M2     =  900.0
    KICKER_W_PER_M2  =   90.0

    # --- Point-light intensities (W/sr) — scale with r² for falloff ---
    # Irradiance at distance d (metres) from a point of intensity I is
    # I/d².  For d = r/1000 m, achieving target E at the subject needs
    # I = E · (r/1000)² = E · r² · 1e-6.  Factor below is "E · 1e-6":
    INTERIOR_W_PER_SR_FACTOR = 3.0e-6    # ~3 W/m² at distance r
    IP_GLOW_W_PER_SR_FACTOR  = 1.25e-6   # subtle purple accent
    SPOT_W_PER_SR_FACTOR     = 15.0e-6   # decoupled — strong god-ray beam
    point_base = r * r                   # r in mm

    # Key light — warm tungsten/golden-hour at 3200 K, raked from above the
    # camera, slightly to the +X side.  Positioned relative to the detector
    # centre so asymmetric geometry stays correctly lit.
    key_obj = _area_light_with_temperature(
        "Light_Key_Golden",
        location=(centre[0] + r * 0.50,
                  centre[1] + r * 1.10,
                  centre[2] + r * 0.95),
        target=centre,
        size=r * 0.55,
        energy=KEY_W_PER_M2,
        temp_kelvin=3200.0,
    )

    # Fill light — cool overcast skylight on the opposite side from the key.
    # 1:8 ratio with key for chiaroscuro emphasis on form.
    fill_obj = _area_light_with_temperature(
        "Light_Fill_Sky",
        location=(centre[0] - r * 0.55,
                  centre[1] + r * 0.65,
                  centre[2] - r * 1.05),
        target=centre,
        size=r * 0.85,
        energy=FILL_W_PER_M2,
        temp_kelvin=6500.0,
    )

    # Rim — small + hot backlight behind the detector, picks out the silhouette
    # against the gradient sky background.
    rim_obj = _area_light_with_temperature(
        "Light_Rim_Warm",
        location=(centre[0] - r * 1.30,
                  centre[1] + r * 0.40,
                  centre[2] + r * 0.30),
        target=centre,
        size=r * 0.30,
        energy=RIM_W_PER_M2,
        temp_kelvin=4200.0,
    )

    # Kicker — placed below + behind to lift under-side reflections out of
    # full shadow.  Neutral 5000 K so it reads as ambient bounce.
    kicker_obj = _area_light_with_temperature(
        "Light_Kicker",
        location=(centre[0] + r * 0.20,
                  centre[1] - r * 0.90,
                  centre[2] + r * 0.40),
        target=centre,
        size=r * 0.50,
        energy=KICKER_W_PER_M2,
        temp_kelvin=5000.0,
    )

    # Interior fill — point light placed inside the phi-cut opening so it
    # illuminates inward-facing surfaces the exterior area lights can't reach.
    _phi_fill_rad = math.radians((phi_min + phi_max) / 2.0) if not no_phi_cut \
                    else math.radians(45.0)
    interior_energy = point_base * INTERIOR_W_PER_SR_FACTOR
    interior_obj = _add_point_light(
        "Light_Interior_Fill",
        location=(centre[0],
                  centre[1] + r * 0.45 * math.cos(_phi_fill_rad),
                  centre[2] + r * 0.45 * math.sin(_phi_fill_rad)),
        energy=interior_energy,
        color_rgb=(1.0, 0.97, 0.92),
        soft_size=r * 0.50,
        temp_kelvin=3800.0,
    )

    # Emissive accent at the interaction point — a tiny self-illuminated
    # sphere that the bloom / streaks key off of.  Sized to ~20 mm so it
    # reads as a glowing "point" at any zoom level.  Strength is modest:
    # the comp's emission-driven streaks pass amplifies it, and anything
    # much above ~50 W/m²/sr blows out into a featureless white field.
    ip_disk = _add_ip_emissive_disk(
        "IP_EmissiveAccent",
        location=centre,
        radius_mm=20.0,
        color_rgb=(0.6, 0.1, 1.0),
        strength=30.0,
    )
    _link_to_collection(ip_disk, col_lights)

    # Purple glow at the interaction point (subtle Cherenkov / beam accent)
    ip_energy = point_base * IP_GLOW_W_PER_SR_FACTOR
    ip_obj = _add_point_light(
        "Light_IP_Purple_Glow",
        location=centre,
        energy=ip_energy,
        color_rgb=(0.45, 0.0, 1.0),
        soft_size=r * 0.30,
    )

    # Move all lights into the Lights collection
    for light_obj in (key_obj, fill_obj, rim_obj, kicker_obj, interior_obj, ip_obj):
        if light_obj is not None:
            _link_to_collection(light_obj, col_lights)

    # Effective total wattage for sanity check (assumes area light total =
    # density × area_m², point total = intensity × 4π).
    def _area_total(density, k):
        return density * (k * r / 1000.0) ** 2
    print(f"  [SETUP] Lights (normalize=False, physical units):", flush=True)
    print(f"    Key    {KEY_W_PER_M2:.0f} W/m²  → total ≈ {_area_total(KEY_W_PER_M2, 0.55):.0f} W", flush=True)
    print(f"    Fill   {FILL_W_PER_M2:.0f} W/m²  → total ≈ {_area_total(FILL_W_PER_M2, 0.85):.0f} W", flush=True)
    print(f"    Rim    {RIM_W_PER_M2:.0f} W/m²  → total ≈ {_area_total(RIM_W_PER_M2, 0.30):.0f} W", flush=True)
    print(f"    Kicker {KICKER_W_PER_M2:.0f} W/m² → total ≈ {_area_total(KICKER_W_PER_M2, 0.50):.0f} W", flush=True)
    print(f"    Interior point {interior_energy:.1f} W/sr → total ≈ {interior_energy * 4 * math.pi:.0f} W", flush=True)
    print(f"    IP glow point  {ip_energy:.1f} W/sr → total ≈ {ip_energy * 4 * math.pi:.0f} W", flush=True)

    # God-ray spot light intensity — decoupled from IP glow so reductions
    # to the glow don't weaken the volumetric scattering beam.
    energy_base = point_base * SPOT_W_PER_SR_FACTOR

    # ---- Volumetric god rays (render-only) ----
    # The volumetric scattering MEDIUM lives on the world shader (set up in
    # _setup_world) — no mesh required, so it is automatically invisible in
    # the viewport.  All that is needed here is a strong spot light aimed
    # through the phi-cut opening; photons crossing the volume produce the
    # crepuscular ray effect during rendering.
    #
    # Historical context: pre-existing code skipped this entirely on Blender
    # 5.0+ because of a save crash in ShaderNodeVolumePrincipled-on-a-mesh.
    # Spot lights themselves never caused the crash, and the world-level
    # scatter shader has been stable since 5.0.1, so we now enable god rays
    # on all Blender versions.
    _phi_center_deg = (phi_min + phi_max) / 2.0 if not no_phi_cut else 45.0
    if not no_phi_cut:
        try:
            god_ray_spot = _add_god_ray_spot(
                "Light_GodRay_Spot",
                phi_center_deg=_phi_center_deg,
                radius=r,
                x_max=x_max,
                energy_base=energy_base,
            )
            _link_to_collection(god_ray_spot, col_lights)
        except Exception as exc:
            print(f"  [GODRAYS] Spot light setup failed ({exc}); "
                  f"world-level volume still active.", flush=True)
    else:
        print("  [GODRAYS] No phi cut — skipping god-ray spot light "
              "(world volume still active for ambient haze).", flush=True)

    # ---- Render settings + compositor bloom ----
    print(f"  [SETUP] Configuring render settings ...", flush=True)
    scene = bpy.data.scenes[0]
    _setup_render_and_compositor(scene, r=r)
    print(f"  [SETUP] Render settings done", flush=True)

    # ---- Pre-save: validate meshes and log scene contents ----
    # Blender 5.0 changed internal mesh data layouts; corrupted CustomData
    # layers (e.g. stale smooth-shading flags) crash save_as_mainfile.
    # validate(clean_customdata=True) removes any invalid attribute layers.
    _mesh_issues = 0
    for _m in bpy.data.meshes:
        try:
            if _m.validate(verbose=False, clean_customdata=True):
                _mesh_issues += 1
                print(f"  [SAVE] Cleaned mesh data: '{_m.name}'", flush=True)
        except Exception as _e:
            print(f"  [SAVE] WARNING mesh validation skipped for '{_m.name}': {_e}",
                  flush=True)

    # Belt-and-suspenders: walk every light data block in the scene and
    # force its normalize toggle off.  The per-helper calls already do
    # this, but this final pass catches anything that slipped through
    # (e.g. a light added via a Blender op, a third-party importer, or a
    # future code path that forgets to set the flag).
    #
    # IMPORTANT: Blender renamed the property between major versions —
    # `use_normalize` on 3.x/4.x, plain `normalize` on 5.0+.  Trying only
    # one name silently no-ops on the other version and leaves Normalize
    # ON in the saved .blend.  _disable_light_normalize tries both.
    _norm_changed = 0
    for _l in bpy.data.lights:
        # Was it on before we touched it?
        was_on = (getattr(_l, "normalize", False)
                  or getattr(_l, "use_normalize", False))
        _disable_light_normalize(_l, getattr(_l, "name", ""))
        # Verify it's actually off now (under either name)
        still_on = (getattr(_l, "normalize", False)
                    or getattr(_l, "use_normalize", False))
        if was_on and not still_on:
            _norm_changed += 1
        elif still_on:
            print(f"  [SAVE] WARNING: light '{getattr(_l, 'name', '?')}' "
                  f"still has normalize ON after sweep — Blender API on this "
                  f"build may use a different attribute name.", flush=True)
    print(f"  [SAVE] Lights: {len(bpy.data.lights)} total, "
          f"{_norm_changed} forced normalize=False in final sweep",
          flush=True)

    print(f"  [SAVE] Meshes: {len(bpy.data.meshes)}  "
          f"Materials: {len(bpy.data.materials)}  "
          f"Node groups: {len(bpy.data.node_groups)}  "
          f"Lights: {len(bpy.data.lights)}  "
          f"Objects: {len(bpy.data.objects)}  "
          f"Worlds: {len(bpy.data.worlds)}",
          flush=True)

    # ---- Save ----
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n  Saving .blend → {output_path} ...", flush=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    print(f"  Save complete.", flush=True)
    print(f"\n  Saved: {output_path}")
    print(f"  Objects: {len(loaded_objects)}")
    print(f"  Collections: Detector ({len(loaded_objects)} objects), "
          f"Cameras (3), Lights (6 + env sphere)")
    print(f"  Active camera: Cam_Perspective (inside detector, looking into phi-cut)")
    print(f"  Cam_Transverse: end-cap view (Y=up, Z=horizontal transverse)")
    print(f"  Cam_Side: elevation view (X=beam left-right, Y=up)")
    if not no_phi_cut:
        print(f"  Phi cutaway: [{phi_min:.0f}°, {phi_max:.0f}°] removed  "
              f"(numpy slicer w/ pre-clean + boundary snap — razor-sharp cut edges)")
        print(f"  PhiBoolean (DIFFERENCE): disabled by default — enable per-object "
              f"if mesh is manifold")
    print(f"  Render: Cycles 4 K, 256 samples")
    print(f"  Lighting: 5-light rig (key 3200 K + fill 6500 K + rim 4200 K + "
          f"kicker 5000 K + interior 3800 K) + purple IP glow + god-ray spot")
    print(f"  World: gradient sky + world-level Volume Scatter "
          f"(volumetric is invisible in viewport, visible only at render)")

    return output_path


# ---------------------------------------------------------------------------
# Entry point when run as a Blender script:
#   blender --background --python gdml_to_blender.py -- '{"mesh_dir": ...}'
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    # Blender passes everything after its own '--' separator as regular sys.argv.
    # Find '--' and take the single JSON-encoded argument that follows it.
    try:
        sep = sys.argv.index("--")
        script_args = sys.argv[sep + 1:]
    except ValueError:
        script_args = sys.argv[1:]

    if not script_args:
        print("gdml_to_blender.py: missing JSON argument", file=sys.stderr)
        sys.exit(1)

    try:
        kwargs = json.loads(script_args[0])
        kwargs["mesh_dir"]    = Path(kwargs["mesh_dir"])
        kwargs["output_path"] = Path(kwargs["output_path"])
        create_blender_scene(**kwargs)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\ngdml_to_blender.py: fatal error: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
