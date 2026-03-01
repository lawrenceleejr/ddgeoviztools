"""
Create a Blender scene (.blend) from per-sub-detector mesh files.

Features
--------
- Reads OBJ / GLTF / VTP mesh files produced by ddgeoviztools' convert step.
- Cleans up duplicate vertices (trimesh process=True + Weld modifier).
- Assigns physics-inspired materials (steel, brass, copper, matte variants).
- Adds a phi-cutaway Geometry Nodes modifier (adjustable via PhiCutawayControl
  empty object — change one property, all sub-detectors update).
- Sets up the scene with GDML geometry imported then rotated +90° around Y
  so that the GDML beam axis (Z) maps to Blender's X axis.  All detector
  objects are also scaled down 100× for a comfortable working viewport.
  Effective Blender convention: X = beam, Y = physics-up (vertical), Z = horizontal transverse.
- Adds pre-positioned orthographic cameras for the two standard HEP views:
    Cam_Transverse  — on +X axis, looks along −X, sees YZ transverse cross-section
    Cam_Side        — on +Z axis, looks along −Z, sees XY (beam=horizontal, Y=up)
    Cam_Perspective — 3/4 overview
- Objects are organised into three named collections: Detector, Cameras, Lights.
- Golden-hour area lights with colour-temperature (Blackbody shader nodes).
- Soft purple glow point light at the interaction-point origin.
- Volumetric world mist (Principled Volume shader).
- Optional microscopic edge chamfering (Bevel modifier) for specular highlights.
- Default render: Cycles 4 K (3840 × 2160), 128 samples, OIDN denoiser,
  Filmic colour management, compositor Glare bloom on the purple glow.
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

# Keyword → (base_RGB, metallic, roughness)
# Matched against the lowercased filename stem of each sub-detector GLTF.
# First match wins; fall back to cycling _PALETTE if nothing matches.
_DETECTOR_MATERIALS = [
    # ECal / EM calorimeter — crystal or lead glass (pale aqua, semi-reflective)
    (("ecal", "emcal", "em_cal", "crystal", "preshower", "pbwo4"),
     (0.35, 0.62, 0.52), 0.10, 0.25),
    # HCal / hadronic calorimeter — iron/brass absorber
    (("hcal", "hcalo", "hadcal", "hcalorimeter"),
     (0.52, 0.38, 0.22), 0.85, 0.40),
    # Solenoid / superconducting coil — bright copper
    (("solenoid", "coil", "solen", "magnet_coil"),
     (0.72, 0.42, 0.22), 0.95, 0.20),
    # Yoke / iron flux return — dark iron
    (("yoke", "iron_yoke", "muon_iron", "flux_return"),
     (0.30, 0.28, 0.26), 0.92, 0.55),
    # Tracker / silicon strips
    (("tracker", "trk", "sit", "svt", "ftd", "set", "etd", "tracking"),
     (0.22, 0.38, 0.60), 0.70, 0.35),
    # TPC — brushed aluminium cylinder
    (("tpc",),
     (0.78, 0.79, 0.80), 0.90, 0.35),
    # Silicon pixel / vertex detector — bright steel blue
    (("pixel", "vxd", "vtx", "velo", "pxd"),
     (0.28, 0.45, 0.72), 0.85, 0.25),
    # Muon detectors (drift tubes, RPCs, …) — matte blue-grey
    (("muon", "mdt", "rpc", "tgc", "csc", "gem", "me0"),
     (0.55, 0.50, 0.68), 0.20, 0.70),
    # TOF / RICH / PID / Cherenkov — gold/brass
    (("tof", "btof", "rich", "dirc", "aerogel", "cherenkov", "pid"),
     (0.68, 0.58, 0.28), 0.80, 0.22),
    # Beam pipe / vacuum chamber — bright stainless steel
    (("beampipe", "beam_pipe", "vacuumchamber", "bpipe"),
     (0.78, 0.79, 0.82), 0.95, 0.12),
    # Nozzle / heavy-metal shielding — dark tungsten-grey
    (("nozzle", "tungsten", "shielding", "shield"),
     (0.28, 0.27, 0.25), 0.85, 0.60),
    # Generic calorimeter label
    (("calorimeter", "calo"),
     (0.42, 0.55, 0.38), 0.10, 0.75),
    # Support / dead material
    (("support", "dead", "frame", "structure"),
     (0.40, 0.40, 0.42), 0.60, 0.65),
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
            bsdf.inputs[key].default_value = 0.5
            break
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


def _phi_cut_trimesh(
    mesh: "trimesh.Trimesh",
    phi_min_deg: float,
    phi_max_deg: float,
) -> "trimesh.Trimesh":
    """
    Remove all triangles whose centroid phi falls inside [phi_min_deg, phi_max_deg].

    phi is measured in the **Blender YZ plane** after the Ry(+90°) rotation that
    maps GDML-Z (beam) → Blender-X.  In local (GDML) coordinates:

        phi_YZ = atan2( -X_local,  Y_local )   [degrees, −180 … +180]

    phi_YZ = 0   → +Y_blender  (vertically up)
    phi_YZ = 90  → +Z_blender  (horizontal transverse, = −X_gdml)

    This is computed and cut entirely in trimesh/numpy — no bpy/bmesh involved —
    so it is safe on Blender 5.0+ where bmesh.ops.delete on large meshes can
    trigger a SIGSEGV inside TBB worker threads.
    """
    if len(mesh.faces) == 0:
        return mesh
    centroids = mesh.triangles_center                          # (N, 3)
    # After Ry(90°): Y_blender = Y_local, Z_blender = -X_local
    # phi_YZ = atan2(Z_blender, Y_blender) = atan2(-X_local, Y_local)
    phi = np.degrees(np.arctan2(-centroids[:, 0], centroids[:, 1]))
    keep = ~((phi >= phi_min_deg) & (phi <= phi_max_deg))
    n_del = int(np.sum(~keep))
    n_tot = len(mesh.faces)
    print(f"    [PHI-TRI] phi=[{phi_min_deg:.1f}°,{phi_max_deg:.1f}°]: "
          f"removing {n_del}/{n_tot} triangles", flush=True)
    keep_idx = np.where(keep)[0]
    if len(keep_idx) == 0:
        return mesh   # safety: never produce an empty mesh
    cut = mesh.submesh([keep_idx], append=True)

    # Close the two open cross-sections left by the phi cut.
    # fill_holes finds every connected boundary-edge loop and triangulates it
    # with a fan from the loop centroid.  For GDML solid volumes the boundary
    # at each cut plane is a roughly rectangular (convex) closed loop per
    # detector layer, so fan triangulation produces correct planar cap faces.
    try:
        trimesh.repair.fill_holes(cut)
        print(f"    [PHI-TRI] Cut faces capped ({len(cut.faces)} faces total)",
              flush=True)
    except Exception as exc:
        print(f"    [PHI-TRI] fill_holes warning: {exc}", flush=True)

    return cut


def _load_mesh(
    filepath: Path,
    name: str,
):
    """
    Read a mesh file with trimesh, merge duplicate vertices and remove
    degenerate faces, then create a bpy Mesh object.

    The phi-sector cutaway is applied as a Boolean modifier (using a separate
    PhiWedge cutter object) rather than being baked into the mesh data here.
    This keeps the cutaway non-destructive and live-adjustable in Blender.

    Returns the new bpy Object.
    """
    # Load without force="mesh": GLTF files return a trimesh.Scene so that
    # _filter_world_volumes can inspect each sub-mesh individually before
    # concatenating.  Using force="mesh" caused trimesh to concatenate all
    # sub-meshes (including the GDML world-volume box) before we could filter.
    raw = trimesh.load(str(filepath), process=False)

    if isinstance(raw, trimesh.Scene):
        # Flatten a multi-mesh scene into one mesh, but first remove any
        # world-volume box that VTK's GLTF exporter embeds in every file.
        # GLTF files can also contain camera/light/curve nodes that trimesh
        # deserialises as Path3D or other non-Trimesh types — drop those first.
        all_geoms = list(raw.geometry.values())
        sub_meshes = [m for m in all_geoms if isinstance(m, trimesh.Trimesh)]
        n_skipped = len(all_geoms) - len(sub_meshes)
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

    verts = raw.vertices.tolist()   # list of [x, y, z]
    faces = raw.faces.tolist()      # list of [i, j, k]

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    # Shade smooth on every face of the base mesh (propagates through modifiers)
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    me.update()

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


def _add_bevel(obj, width_mm: float = 0.2):
    """
    Add a Bevel modifier with a tiny chamfer on sharp edges.

    This adds micro-chamfers at angle-limited edges, which catches
    specular highlights and gives the detector components a more
    manufactured, physically-accurate appearance.

    Parameters
    ----------
    width_mm : chamfer width in mm. 0.2 mm is microscopic — just enough
               to produce a specular glint without visibly changing shape.
               Set to 0 to skip.
    """
    if width_mm <= 0:
        return None
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width = max(1e-6, width_mm)
    mod.segments = 2
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(30)   # only sharp edges (>30°)
    mod.use_clamp_overlap = True
    mod.profile = 0.5
    # harden_normals was removed from the Bevel modifier in Blender 4.2+
    try:
        mod.harden_normals = True
    except AttributeError:
        pass
    return mod


# ---------------------------------------------------------------------------
# Phi-cutaway Geometry Node group
# ---------------------------------------------------------------------------

def _apply_phi_cutaway_bmesh(obj, phi_min_deg: float, phi_max_deg: float):
    """
    Apply phi cutaway by deleting faces whose centroid phi lies *inside*
    [phi_min_deg, phi_max_deg].  This removes a wedge-shaped sector from the
    detector so the interior is visible — everything *outside* the range is
    kept.

    phi = atan2(Y, X) in radians; Z is the beam axis.
    """
    import bmesh
    phi_min = math.radians(phi_min_deg)
    phi_max = math.radians(phi_max_deg)
    n_faces = len(obj.data.polygons)
    print(f"  [PHI-BMESH] Cutting sector [{phi_min_deg:.1f}°, {phi_max_deg:.1f}°] "
          f"from '{obj.name}' ({n_faces} faces) ...",
          flush=True)

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    del_faces = []
    for f in bm.faces:
        n = len(f.verts)
        cx = sum(v.co.x for v in f.verts) / n
        cy = sum(v.co.y for v in f.verts) / n
        # Use Blender-YZ convention: phi = atan2(-X_local, Y_local)
        # (phi=0 → +Y_blender, phi=90 → +Z_blender)
        phi = math.atan2(-cx, cy)
        # Delete faces whose phi falls inside the cut sector
        if phi_min <= phi <= phi_max:
            del_faces.append(f)

    print(f"  [PHI-BMESH]   → deleting {len(del_faces)} / {len(bm.faces)} faces",
          flush=True)
    bmesh.ops.delete(bm, geom=del_faces, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    print(f"  [PHI-BMESH]   → done; {len(obj.data.polygons)} faces remain", flush=True)


def _precompute_phi_face_attribute(obj):
    """
    Compute phi = atan2(Y, X) in degrees for every face centroid and store
    it as a float FACE attribute named 'phi_deg' on the mesh.

    Required for the Blender 5.0+ phi-cutaway node group, which cannot use
    ShaderNodeMath to compute atan2 inside a GeometryNodeTree.  The GN
    modifier reads this pre-computed attribute via GeometryNodeInputNamedAttribute
    so it only needs FunctionNodeCompare / FunctionNodeBooleanMath — nodes
    that remain valid in Blender 5.0+ geometry node trees.
    """
    mesh = obj.data
    phi_values = []
    for poly in mesh.polygons:
        verts = poly.vertices
        cx = sum(mesh.vertices[vi].co.x for vi in verts) / len(verts)
        cy = sum(mesh.vertices[vi].co.y for vi in verts) / len(verts)
        # Blender-YZ convention: phi = atan2(-X_local, Y_local)
        phi_values.append(math.degrees(math.atan2(-cx, cy)))

    attr = mesh.attributes.new("phi_deg", "FLOAT", "FACE")
    for i, v in enumerate(phi_values):
        attr.data[i].value = v


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

    Default phi_min=0, phi_max=90 shows the first quadrant (upper right).
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
    merge = N("GeometryNodeMergeByDistance",  -600,  100)
    merge.inputs["Distance"].default_value = 1e-4
    merge.label = "Weld seam duplicates"

    # Delete faces outside phi range
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

    # Combine and invert
    links.new(gt.outputs["Value"],        mul.inputs[0])
    links.new(lt.outputs["Value"],        mul.inputs[1])
    links.new(mul.outputs["Value"],       sub.inputs[1])

    # Delete geometry
    links.new(merge.outputs["Geometry"],  delete.inputs["Geometry"])
    links.new(sub.outputs["Value"],       delete.inputs["Selection"])
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
      FunctionNodeBooleanMath          — AND the two → inside; NOT → outside
      GeometryNodeDeleteGeometry       — delete faces where outside is True

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
        not_node  = N("FunctionNodeBooleanMath",             100,    0)
        delete    = N("GeometryNodeDeleteGeometry",          320,    0)

        missing = [name for name, n in (
            ("NodeGroupInput",                  g_in),
            ("NodeGroupOutput",                 g_out),
            ("GeometryNodeInputNamedAttribute", attr_node),
            ("FunctionNodeCompare (GT)",        gt),
            ("FunctionNodeCompare (LT)",        lt),
            ("FunctionNodeBooleanMath (AND)",   and_node),
            ("FunctionNodeBooleanMath (NOT)",   not_node),
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
        and_node.operation = "AND";  and_node.label = "inside"
        not_node.operation = "NOT";  not_node.label = "outside"
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
        L(and_node.outputs[0],      not_node.inputs[0],       "AND→NOT")
        L(g_in.outputs["Geometry"], delete.inputs["Geometry"],"Geo→DEL")
        L(not_node.outputs[0],      delete.inputs["Selection"],"NOT→DEL.sel")
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

    print(f"  [PHI] Socket identifiers: Phi Min={id_min!r}  Phi Max={id_max!r}", flush=True)

    # In Blender 5.0+ the GN modifier input storage changed; driver paths of the
    # form mod["Socket_X"] may no longer map to valid FCurve targets and a
    # half-configured FCurve will crash save_as_mainfile with SIGSEGV.
    # Skip driver wiring on 5.0+ — the modifier still applies the cutaway at
    # the baked default values; drivers can be re-added manually if needed.
    _skip_drivers = bpy.app.version >= (5, 0, 0)
    if _skip_drivers:
        print("  [PHI] Blender 5.0+: skipping driver wiring to avoid serialiser crash.",
              flush=True)

    for identifier, prop_name, default in (
        (id_min, "phi_min", phi_min),
        (id_max, "phi_max", phi_max),
    ):
        if identifier is None:
            continue
        mod[identifier] = default

        if _skip_drivers:
            continue

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
            # Log and clean up — a partial FCurve is worse than none.
            print(f"  [PHI] Driver warning ({identifier!r}): {exc}", flush=True)
            if fc is not None:
                try:
                    mod.driver_remove(f'["{identifier}"]')
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Live phi-wedge Boolean cutter
# ---------------------------------------------------------------------------

def _make_phi_wedge_node_group(phi_min_deg: float, phi_max_deg: float):
    """
    Build a Geometry Nodes group that trims a full cylinder to the angular
    sector [phi_min_deg, phi_max_deg] by reading the pre-baked 'phi_deg'
    FACE attribute.

    Blender 5.0+ compatible — uses only:
      GeometryNodeInputNamedAttribute, FunctionNodeCompare,
      FunctionNodeBooleanMath, GeometryNodeDeleteGeometry.

    The Phi Min / Phi Max GROUP INPUTS are exposed in the modifier panel so
    the sector can be edited live without re-running any Python.
    """
    NG_NAME = "PhiWedgeGen"
    if NG_NAME in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[NG_NAME])

    ng    = bpy.data.node_groups.new(NG_NAME, "GeometryNodeTree")
    iface = ng.interface
    nodes = ng.nodes
    links = ng.links

    # ---- Interface ----
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
    s_min = iface.new_socket("Phi Min", in_out="INPUT", socket_type="NodeSocketFloat")
    s_max = iface.new_socket("Phi Max", in_out="INPUT", socket_type="NodeSocketFloat")
    s_min.default_value = phi_min_deg
    s_max.default_value = phi_max_deg

    gin  = nodes.new("NodeGroupInput");  gin.location  = (-600,   0)
    gout = nodes.new("NodeGroupOutput"); gout.location  = ( 700,   0)

    # Read 'phi_deg' float face attribute (pre-baked on the cylinder mesh)
    attr           = nodes.new("GeometryNodeInputNamedAttribute")
    attr.data_type = "FLOAT"
    attr.inputs[0].default_value = "phi_deg"
    attr.location  = (-400, -150)

    # phi_deg >= Phi Min
    cmp_min           = nodes.new("FunctionNodeCompare")
    cmp_min.data_type = "FLOAT"
    cmp_min.operation = "GREATER_EQUAL"
    cmp_min.location  = (-180,  120)

    # phi_deg <= Phi Max
    cmp_max           = nodes.new("FunctionNodeCompare")
    cmp_max.data_type = "FLOAT"
    cmp_max.operation = "LESS_EQUAL"
    cmp_max.location  = (-180, -120)

    # AND: face is inside sector
    and_nd           = nodes.new("FunctionNodeBooleanMath")
    and_nd.operation = "AND"
    and_nd.location  = (  60,    0)

    # NOT: select faces to delete (those outside the sector)
    not_nd           = nodes.new("FunctionNodeBooleanMath")
    not_nd.operation = "NOT"
    not_nd.location  = ( 260,  -80)

    del_geo        = nodes.new("GeometryNodeDeleteGeometry")
    del_geo.domain = "FACE"
    del_geo.mode   = "ALL"
    del_geo.location = (480, 0)

    # ---- Wiring ----
    links.new(gin.outputs["Geometry"],  del_geo.inputs["Geometry"])
    links.new(attr.outputs[0],          cmp_min.inputs["A"])
    links.new(gin.outputs["Phi Min"],   cmp_min.inputs["B"])
    links.new(attr.outputs[0],          cmp_max.inputs["A"])
    links.new(gin.outputs["Phi Max"],   cmp_max.inputs["B"])
    links.new(cmp_min.outputs[0],       and_nd.inputs[0])
    links.new(cmp_max.outputs[0],       and_nd.inputs[1])
    links.new(and_nd.outputs[0],        not_nd.inputs[0])
    links.new(not_nd.outputs[0],        del_geo.inputs["Selection"])
    links.new(del_geo.outputs[0],       gout.inputs["Geometry"])

    print(f"  [WEDGE] PhiWedgeGen GN group built "
          f"({len(ng.nodes)} nodes, {len(ng.links)} links)", flush=True)
    return ng


def _create_phi_wedge_cutter(
    phi_min_deg: float,
    phi_max_deg: float,
    radius: float,
    depth: float,
    collection,
):
    """
    Create a solid pie-slice cylinder for use as a Boolean DIFFERENCE cutter.

    Geometry convention (Blender world coords, after the Ry+90° detector rotation):
        X = beam,  Y = physics-up (phi = 0°),  Z = horiz-transverse (phi = 90°).
    phi_deg = atan2(Z, Y)  — matches the Blender-YZ phi labelling on the detectors.

    The wedge is built directly as a closed, manifold solid so that Blender's
    Boolean DIFFERENCE modifier correctly removes the phi sector from detector
    objects.  The previous approach (full 360° cylinder trimmed by a GN modifier)
    produced an open mesh with disconnected boundary-wall vertices, which caused
    the Boolean to fail silently.

    The cutter is shown as wireframe in the viewport and excluded from renders;
    the Boolean modifier on detector objects still references it as its operand.
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

    # Outer arc wall — side quads (normals point radially outward)
    for i in range(N_ARC):
        bm.faces.new([vp[i], vp[i + 1], vn[i + 1], vn[i]])

    # +X end-cap: fan of triangles from centre (normal → +X)
    for i in range(N_ARC):
        bm.faces.new([vc_pos, vp[i + 1], vp[i]])

    # −X end-cap: fan of triangles from centre (normal → −X)
    for i in range(N_ARC):
        bm.faces.new([vc_neg, vn[i], vn[i + 1]])

    # Radial wall at phi_min (normal points away from sector interior)
    bm.faces.new([vc_pos, vc_neg, vn[0], vp[0]])

    # Radial wall at phi_max (normal points away from sector interior)
    bm.faces.new([vc_pos, vp[N_ARC], vn[N_ARC], vc_neg])

    # Ensure consistent outward-pointing normals for the Boolean solver
    _bm.ops.recalc_face_normals(bm, faces=bm.faces[:])

    bm.to_mesh(me)
    bm.free()
    me.update()

    obj = bpy.data.objects.new("PhiWedge", me)
    bpy.data.scenes[0].collection.objects.link(obj)

    # Wireframe-only in viewport — user can see/select it but it won't obscure
    # the detector.  Excluded from renders entirely.
    obj.display_type = "WIRE"
    obj.hide_render  = True

    _link_to_collection(obj, collection)
    print(f"  [WEDGE] PhiWedge cutter: "
          f"phi=[{phi_min_deg:.1f}°,{phi_max_deg:.1f}°] "
          f"r={r:.1f} depth={depth:.1f} BU", flush=True)
    return obj


def _apply_boolean_phi_cut(det_obj, wedge_obj):
    """
    Add a Boolean DIFFERENCE modifier to *det_obj* that uses *wedge_obj* as
    the cutter.

    Blender 5.0 renamed the fast/float solver: 'FAST' → 'FLOAT'.
    Try the version-appropriate name and fall back silently.
    """
    mod           = det_obj.modifiers.new("PhiBoolean", "BOOLEAN")
    mod.operation = "DIFFERENCE"
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
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
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


# ---------------------------------------------------------------------------
# Lighting — golden-hour area lights with colour temperature
# ---------------------------------------------------------------------------

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
    using Blender's blackbody mechanism — not an RGB approximation.

    Tries, in order:
      1. light_data.color_mode = 'TEMPERATURE'  (Blender 4.0+ native property)
      2. ShaderNodeBlackbody in the light's node tree  (Blender 3.x)
      3. _kelvin_to_rgb RGB fallback (should never be reached in normal use)
    """
    # --- Attempt 1: native color_mode = 'TEMPERATURE' (Blender 4.0+) ---
    if hasattr(light_data, "color_mode"):
        try:
            light_data.color_mode = "TEMPERATURE"
            light_data.temperature = float(temp_kelvin)
            print(f"  [LIGHT] {name}  {energy:.0f} W  "
                  f"{temp_kelvin:.0f} K  (native color_mode=TEMPERATURE)",
                  flush=True)
            return
        except Exception as exc:
            print(f"  [LIGHT] {name}  color_mode=TEMPERATURE failed: {exc}",
                  flush=True)

    # On Blender 5.0+ skip the ShaderNodeBlackbody-in-light-tree approach.
    # Those node trees crash save_as_mainfile on 5.0 (same root cause as the
    # world Principled Volume crash).  Fall straight through to RGB approx.
    if bpy.app.version >= (5, 0, 0):
        r, g, b = _kelvin_to_rgb(temp_kelvin)
        light_data.color = (r, g, b)
        print(f"  [LIGHT] {name}  {energy:.0f} W  "
              f"{temp_kelvin:.0f} K → rgb({r:.3f},{g:.3f},{b:.3f})  "
              f"(RGB approx — Blackbody node skipped on Blender 5+)",
              flush=True)
        return

    # --- Attempt 2: ShaderNodeBlackbody in node tree (Blender 3.x / 4.x) ---
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
):
    """
    Create a point light with a fixed colour (not temperature-based).

    soft_size controls the shadow softness radius.
    """
    light_data        = bpy.data.lights.new(name, type="POINT")
    light_data.energy = energy
    light_data.color  = color_rgb
    # shadow_soft_size was renamed/removed in Blender 5.0; try the new name first
    if hasattr(light_data, "shadow_source_angle"):
        light_data.shadow_source_angle = soft_size * 0.01  # rough conversion
    elif hasattr(light_data, "shadow_soft_size"):
        light_data.shadow_soft_size = soft_size

    light_obj = bpy.data.objects.new(name, light_data)
    bpy.data.scenes[0].collection.objects.link(light_obj)
    light_obj.location = Vector(location)
    return light_obj


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
    Volume Scatter is added to the material's Volume socket while leaving the
    existing Principled BSDF → Surface connection in place.  Keeping the
    surface shader prevents the "Using fallback" crash that occurs in Blender
    5.0 when save_as_mainfile serialises a material whose Surface socket is
    empty.  The sphere's surface is set fully transparent so only the volume
    contribution is visible in renders.
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

    # Volume Scatter material.
    # IMPORTANT: do NOT call nodes.clear() — removing the Surface shader
    # produces a material with an empty Surface socket which crashes Blender
    # 5.0 save_as_mainfile.  Instead keep the default Principled BSDF (set
    # Alpha=0 so it's transparent) and wire Volume Scatter into the Volume
    # socket of the same Material Output node.
    mat = bpy.data.materials.new("GodRayScatter")
    # Blender 5+: node_tree is always present; Blender 4.x needs use_nodes=True.
    if mat.node_tree is None:
        mat.use_nodes = True
    tree  = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    # Make the surface fully transparent (alpha=0) so only volume is visible
    bsdf = nodes.get("Principled BSDF")
    if bsdf and "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = 0.0
    # Enable alpha blending so the transparent surface doesn't occlude the volume.
    # Property name changed between Blender 4.x and 5.x — try both.
    try:
        mat.blend_method = "BLEND"          # Blender 4.x
    except (AttributeError, TypeError):
        try:
            mat.surface_render_method = "BLENDED"   # Blender 5.x
        except (AttributeError, TypeError):
            pass

    # Find or create the Material Output node
    out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None:
        out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)

    # Add Volume Scatter and wire to Volume socket
    scatter = nodes.new("ShaderNodeVolumeScatter")
    scatter.inputs["Density"].default_value    = 3e-4   # subtle atmospheric haze
    scatter.inputs["Anisotropy"].default_value = 0.6    # forward-scatter → ray glints
    scatter.location = (0, -150)
    links.new(scatter.outputs["Volume"], out.inputs["Volume"])

    obj.data.materials.append(mat)
    print(f"  [GODRAYS] Volume scatter sphere: radius={radius:.1f} BU "
          f"density=3e-4 anisotropy=0.6  (render-only)", flush=True)
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

    light_data        = bpy.data.lights.new(name, type="SPOT")
    light_data.energy = energy_base * 600.0
    light_data.color  = (0.95, 0.92, 0.80)     # warm golden-white
    light_data.spot_size   = math.radians(35)   # 35° cone — wide enough to fill opening
    light_data.spot_blend  = 0.25               # soft penumbra
    # Shadow cast ON so the beam terminates at detector surfaces (essential for rays)
    try:
        light_data.use_shadow = True
    except AttributeError:
        pass

    light_obj = bpy.data.objects.new(name, light_data)
    bpy.data.scenes[0].collection.objects.link(light_obj)
    light_obj.location = Vector(loc)

    direction = (Vector(target) - Vector(loc)).normalized()
    light_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # Render-only: hidden from viewport so it doesn't clutter editing
    light_obj.hide_viewport = True
    light_obj.hide_render   = False

    print(f"  [GODRAYS] Spot light '{name}'  phi={phi_center_deg:.1f}°  "
          f"energy={energy_base * 600:.0f} W  (render-only)", flush=True)
    return light_obj


# ---------------------------------------------------------------------------
# World shader — dark space background + volumetric mist
# ---------------------------------------------------------------------------

def _setup_world():
    """
    Configure the world shader:
    - Near-black background (deep space blue)
    - Subtle volumetric mist via Principled Volume (Blender 4.x only)

    Blender 5.0 changed ShaderNodeVolumePrincipled internals; including it in
    the world node tree causes save_as_mainfile to crash with SIGSEGV.  On
    Blender 5.0+ we use a plain Background node only — same colour, no volume.
    """
    if bpy.data.worlds:
        world = bpy.data.worlds[0]
    else:
        world = bpy.data.worlds.new("World")
    bpy.data.scenes[0].world = world
    # Blender 5+: world always uses nodes; use_nodes is deprecated.
    if world.node_tree is None:
        world.use_nodes = True

    tree  = world.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    # Background — deep space blue, bright enough to provide soft ambient fill
    # on interior surfaces not directly reached by the key/fill lights.
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value    = (0.02, 0.02, 0.05, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    bg.location = (0, 100)

    out = nodes.new("ShaderNodeOutputWorld")
    out.location = (400, 0)

    if bpy.app.version >= (5, 0, 0):
        # Skip volumetric mist — ShaderNodeVolumePrincipled crashes on save in 5.0
        links.new(bg.outputs["Background"], out.inputs["Surface"])
        print("  [WORLD] Background only (volume skipped on Blender 5.0+)", flush=True)
    else:
        # Volumetric mist — extremely low density, just a hint
        vol = nodes.new("ShaderNodeVolumePrincipled")
        vol.inputs["Density"].default_value    = 1e-6
        vol.inputs["Anisotropy"].default_value = 0.2
        for key in ("Scatter Color", "Scattering Color"):
            if key in vol.inputs:
                vol.inputs[key].default_value = (0.70, 0.80, 1.0, 1.0)
                break
        vol.location = (0, -100)
        links.new(bg.outputs["Background"], out.inputs["Surface"])
        links.new(vol.outputs["Volume"],    out.inputs["Volume"])
        print("  [WORLD] Background + Principled Volume mist", flush=True)


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


def _setup_render_and_compositor(scene):
    """
    Configure Cycles render settings (4 K, 128 samples, OIDN denoiser)
    and add a compositor Glare node for bloom on the purple IP light.
    """
    # Engine
    scene.render.engine = "CYCLES"

    # Resolution — 4 K UHD
    scene.render.resolution_x          = 3840
    scene.render.resolution_y          = 2160
    scene.render.resolution_percentage = 100

    # Cycles samples
    scene.cycles.samples         = 128
    scene.cycles.use_denoising  = True
    try:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass  # older / newer bpy builds may not accept the string assignment

    # Colour management — Filmic for cinematic look.
    # A positive exposure offset lifts the scene brightness in the viewport
    # and in renders; without it Filmic tone-mapping can make scenes appear
    # very dark when the dominant light is a distant area source.
    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look           = "Medium Contrast"
        scene.view_settings.exposure       = 2.0   # +2 EV → brighter viewport
    except Exception:
        pass

    # Compositor — Glare node for IP glow bloom.
    # The compositor API changed substantially in Blender 5.0 (node properties
    # removed, node graph restructured) and a half-built graph causes a process
    # crash on save.  Skip entirely on 5.0+; render settings above are intact.
    if bpy.app.version >= (5, 0, 0):
        print("  [INFO] Compositor bloom skipped (Blender 5.0+ compositor API changed).",
              flush=True)
        return

    ctree = _get_compositor_tree(scene)
    if ctree is None:
        print("  [WARN] Could not access compositor node tree; skipping bloom setup.",
              flush=True)
        return

    cnodes = ctree.nodes
    clinks = ctree.links
    cnodes.clear()

    render_layer = cnodes.new("CompositorNodeRLayers")
    render_layer.location = (-400, 0)

    glare = cnodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    glare.size       = 7
    glare.threshold  = 0.8
    glare.quality    = "HIGH"
    glare.mix        = 0.0
    glare.location   = (0, 0)

    composite = cnodes.new("CompositorNodeComposite")
    composite.location = (400, 0)

    clinks.new(render_layer.outputs["Image"], glare.inputs["Image"])
    clinks.new(glare.outputs["Image"],        composite.inputs["Image"])


# ---------------------------------------------------------------------------
# Camera helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Scene bounds helper
# ---------------------------------------------------------------------------

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
    mesh_dir:       Path,
    output_path:    Path,
    fmt:            str   = "gltf",
    phi_min:        float = 0.0,
    phi_max:        float = 90.0,
    no_phi_cut:     bool  = False,
    weld_threshold: float = 1e-4,
    bevel_width_mm: float = 0.2,
    no_bevel:       bool  = False,
    no_env_sphere:  bool  = False,
) -> Path:
    """
    Build and save a Blender scene from a directory of mesh files.

    Parameters
    ----------
    mesh_dir       : directory containing *.{fmt} files (one per sub-detector)
    output_path    : where to write the .blend file
    fmt            : input mesh format ('gltf', 'glb', 'obj', 'vtp')
    phi_min        : phi cut-sector start angle (degrees, default 0).
                     Faces whose centroid phi lies in [phi_min, phi_max] are
                     removed, exposing the detector interior.
    phi_max        : phi cut-sector end angle (degrees, default 90)
    no_phi_cut     : if True, skip phi-cutaway entirely (show full detector)
    weld_threshold : distance for Weld modifier in mm (default 1e-4)
    bevel_width_mm : edge chamfer width in mm for specular highlights (default 0.2)
    no_bevel       : if True, skip the Bevel modifier
    no_env_sphere  : if True, skip the matte environment sphere
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
    print(f"  [SETUP] Collections created: Detector, Cameras, Lights, Cutters", flush=True)

    # ---- World shader (background + volumetric mist) ----
    print(f"  [SETUP] Setting up world shader ...", flush=True)
    _setup_world()

    # ---- Pre-create materials ----
    print(f"  [SETUP] Pre-creating materials ...", flush=True)
    materials = _pre_create_materials()
    mat_cycle = cycle(materials)
    print(f"  [SETUP] {len(materials)} materials ready: "
          f"{[m.name for m in materials]}", flush=True)

    # ---- Load each mesh ----
    # Phi cutaway is now a live Boolean modifier (PhiBoolean) applied after
    # scene bounds are computed.  Meshes are loaded clean — no baking.
    if not no_phi_cut:
        print(f"  [PHI] Phi cutaway [{phi_min:.1f}°, {phi_max:.1f}°] will be applied "
              f"as a Boolean modifier (PhiWedge cutter, live-adjustable via GN).",
              flush=True)

    loaded_objects: list = []
    for mesh_path in mesh_files:
        name = mesh_path.stem
        print(f"  Loading {mesh_path.name} ...")
        try:
            obj = _load_mesh(mesh_path, name)
        except Exception as exc:
            print(f"  [WARN] Could not load {mesh_path.name}: {exc}", file=sys.stderr)
            continue

        # Material — try to infer from the sub-detector name, else cycle palette
        mat = _material_for_detector(name, mat_cycle)
        obj.data.materials.append(mat)

        # Weld only here; Boolean + Bevel are added after scene bounds are known
        _add_weld(obj, threshold=weld_threshold)

        # Rotate beam axis: GDML/GLTF convention has Z = beam direction.
        # Rotate +90° around Y so that Z_gdml → X_blender, making the beam
        # line horizontal along the Blender X axis.
        # Scale down 100× so the detector fits comfortably in Blender's
        # working viewport (e.g. solenoid goes from ±2300 BU to ±23 BU).
        obj.rotation_euler = (0.0, math.radians(90.0), 0.0)
        obj.scale = (0.01, 0.01, 0.01)

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
    # After the Ry(+90°) rotation and 0.01 scale applied to every object:
    #   x_max = beam half-length   (was z_gdml)
    #   y_max = vertical transverse  (was y_gdml)
    #   z_max = horizontal transverse (was x_gdml, sign-flipped but abs same)
    x_max, y_max, z_max = _scene_bounds(loaded_objects)
    r = max(x_max, y_max, z_max)   # overall scale radius (Blender units)

    # Transverse view (end-cap): camera distance based on transverse extent
    r_trans  = max(y_max, z_max) * 1.6
    # Side/elevation view: camera distance based on beam + vertical extent
    r_side   = max(x_max, y_max) * 1.6
    r_persp  = r * 2.2

    ortho_trans = max(y_max, z_max) * 2.2
    ortho_side  = max(x_max, y_max) * 2.2

    # ---- Phi-wedge Boolean cutter ----
    # Created after scene bounds so the wedge is sized to fully cover the detector.
    # Applied as the second modifier (after Weld, before Bevel) so edge-chamfering
    # works on the cut surface too.
    wedge_obj = None
    if not no_phi_cut:
        # Wedge radius: 2× transverse extent covers the detector plus margin.
        # Depth: 3× beam extent so the wedge fully brackets the longest detector.
        w_radius = max(y_max, z_max) * 2.5
        w_depth  = x_max * 3.0
        wedge_obj = _create_phi_wedge_cutter(
            phi_min, phi_max, w_radius, w_depth, col_cutters
        )
        # Boolean + Bevel: second pass over every loaded detector object
        for obj in loaded_objects:
            _apply_boolean_phi_cut(obj, wedge_obj)
            if not no_bevel:
                _add_bevel(obj, width_mm=bevel_width_mm)
        print(f"  [PHI] Boolean phi-cut applied to {len(loaded_objects)} objects",
              flush=True)
    else:
        # No phi cut — just add Bevel
        for obj in loaded_objects:
            if not no_bevel:
                _add_bevel(obj, width_mm=bevel_width_mm)

    # ---- Environment sphere ----
    if not no_env_sphere:
        env_sphere = _add_environment_sphere(r * 1.8)
        _link_to_collection(env_sphere, col_lights)

    # ---- Cameras ----
    print(f"  [SETUP] Creating cameras "
          f"(r_trans={r_trans:.2f} r_side={r_side:.2f} r_persp={r_persp:.2f}) ...",
          flush=True)

    # Transverse (end-cap): camera on +X axis (beam direction) looking toward origin.
    #   → sees YZ plane: Y = physics-up (vertical), Z = physics-horizontal-transverse.
    #   In GDML terms this is the transverse cross-section of the detector.
    cam_trans = _make_camera(
        "Cam_Transverse",
        location=(r_trans, 0, 0),
        target=(0, 0, 0),
        ortho=True,
        ortho_scale=ortho_trans,
    )

    # Side / elevation: camera on +Z axis looking down toward origin.
    #   → sees XY plane: X = beam (horizontal right), Y = physics-up (vertical).
    #   This gives the classic "side view" with the beam axis running left–right.
    _make_camera(
        "Cam_Side",
        location=(0, 0, r_side),
        target=(0, 0, 0),
        ortho=True,
        ortho_scale=ortho_side,
    )

    # Perspective camera — placed at the interaction point (inside the detector),
    # looking out through the phi-cut opening so the viewer sees all detector
    # layers framed by the cut.
    # phi_center is the bisector of the cut in Blender-YZ convention.
    if no_phi_cut:
        _phi_center_rad = math.radians(45.0)
    else:
        _phi_center_rad = math.radians((phi_min + phi_max) / 2.0)

    # Target: centre of the cut opening at the outer detector radius
    _cam_target_Y = r * math.cos(_phi_center_rad)
    _cam_target_Z = r * math.sin(_phi_center_rad)
    # Location: slightly off-axis along beam so the direction vector is nonzero
    _cam_loc_X = x_max * 0.05
    cam_persp = _make_camera(
        "Cam_Perspective",
        location=(_cam_loc_X, 0.0, 0.0),
        target=(0.0, _cam_target_Y, _cam_target_Z),
        ortho=False,
    )

    # Move cameras into the Cameras collection
    for cam_name in ("Cam_Transverse", "Cam_Side", "Cam_Perspective"):
        cam_obj = bpy.data.objects.get(cam_name)
        if cam_obj:
            _link_to_collection(cam_obj, col_cameras)

    # Set active camera to the perspective view (inside the detector)
    bpy.data.scenes[0].camera = cam_persp
    print(f"  [SETUP] Cameras created (active: Cam_Perspective, inside detector, "
          f"looking into phi-cut at {math.degrees(_phi_center_rad):.0f}°)", flush=True)

    # ---- Lighting ----
    print(f"  [SETUP] Creating lights ...", flush=True)
    # Three-point golden-hour area lights with colour temperature.
    # After the 100× scale reduction, r is ~23–60 Blender units (representing
    # a real detector of ~3–12 m scale). The r² formula gives energies in the
    # tens-to-hundreds of watts — appropriate for Blender Cycles at this scale.
    # Positions are given in Blender world coords (X = beam, Y = physics-up,
    # Z = physics-horizontal-transverse).
    # Energy scales with r² so that light covers the scene regardless of size.
    # Multipliers are tuned so that the Cycles render at default exposure is
    # properly lit; interior surfaces (visible through the phi cut) receive
    # fill from the interior fill light and the raised world-background strength.
    energy_base = r * r * 0.0005   # W · BU⁻²

    # Key light — warm golden-hour glow from above and slightly to one side.
    # 3000 K ≈ incandescent / warm candlelight.
    key_obj = _area_light_with_temperature(
        "Light_Key_Golden",
        location=( r * 0.40,  r * 1.20,  r * 0.90),
        target=(0, 0, 0),
        size=r * 0.60,
        energy=energy_base * 400.0,
        temp_kelvin=3000.0,
    )

    # Fill light — cooler sky blue from the opposite side and slightly behind.
    # 7500 K ≈ overcast skylight.
    fill_obj = _area_light_with_temperature(
        "Light_Fill_Sky",
        location=(-r * 0.50,  r * 0.70, -r * 1.00),
        target=(0, 0, 0),
        size=r * 0.48,
        energy=energy_base * 72.0,
        temp_kelvin=7500.0,
    )

    # Rim light — warm backlight along the −beam direction to separate the
    # detector silhouette from the dark background.
    # 4500 K ≈ neutral warm white.
    rim_obj = _area_light_with_temperature(
        "Light_Rim_Warm",
        location=(-r * 1.30,  r * 0.30,  r * 0.20),
        target=(0, 0, 0),
        size=r * 0.30,
        energy=energy_base * 120.0,
        temp_kelvin=4500.0,
    )

    # Interior fill — point light placed inside the phi-cut opening so it
    # illuminates the inward-facing detector surfaces that the exterior area
    # lights cannot directly reach.  Positioned halfway along the cut bisector.
    _phi_fill_rad = math.radians((phi_min + phi_max) / 2.0) if not no_phi_cut \
                    else math.radians(45.0)
    interior_obj = _add_point_light(
        "Light_Interior_Fill",
        location=(0.0, r * 0.45 * math.cos(_phi_fill_rad),
                       r * 0.45 * math.sin(_phi_fill_rad)),
        energy=energy_base * 300.0,
        color_rgb=(1.0, 0.97, 0.92),   # near-white / warm white
        soft_size=r * 0.50,
    )

    # Purple glow at the interaction point (IP / beam origin)
    # Soft point light — evocative of Cherenkov / beam interactions.
    ip_obj = _add_point_light(
        "Light_IP_Purple_Glow",
        location=(0, 0, 0),
        energy=energy_base * 80.0,
        color_rgb=(0.45, 0.0, 1.0),
        soft_size=r * 0.30,
    )

    # Move all lights (including environment sphere) into the Lights collection
    for light_obj in (key_obj, fill_obj, rim_obj, interior_obj, ip_obj):
        if light_obj is not None:
            _link_to_collection(light_obj, col_lights)

    print(f"  [SETUP] Lights created (energy_base={energy_base:.3f} W, "
          f"key={energy_base*400:.0f} W, fill={energy_base*72:.0f} W, "
          f"rim={energy_base*120:.0f} W, interior={energy_base*300:.0f} W, "
          f"IP={energy_base*80:.0f} W)", flush=True)

    # ---- Volumetric god rays (render-only) ----
    # A large Volume Scatter sphere (hidden from viewport, visible in render)
    # provides the participating medium.  A spot light aimed through the
    # phi-cut opening scatters photons inside this medium, producing visible
    # light shafts (god rays) when rendered with Cycles.
    # Both objects are render-only so they never clutter the editing viewport.
    _phi_center_deg = (phi_min + phi_max) / 2.0 if not no_phi_cut else 45.0
    vol_sphere = _add_volume_scatter_sphere(r * 1.75)
    _link_to_collection(vol_sphere, col_lights)
    if not no_phi_cut:
        god_ray_spot = _add_god_ray_spot(
            "Light_GodRay_Spot",
            phi_center_deg=_phi_center_deg,
            radius=r,
            x_max=x_max,
            energy_base=energy_base,
        )
        _link_to_collection(god_ray_spot, col_lights)

    # ---- Render settings + compositor bloom ----
    print(f"  [SETUP] Configuring render settings ...", flush=True)
    scene = bpy.data.scenes[0]
    _setup_render_and_compositor(scene)
    print(f"  [SETUP] Render settings done", flush=True)

    # ---- Save ----
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n  Saving .blend → {output_path} ...", flush=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    print(f"  Save complete.", flush=True)
    print(f"\n  Saved: {output_path}")
    print(f"  Objects: {len(loaded_objects)}")
    print(f"  Collections: Detector ({len(loaded_objects)} objects), "
          f"Cameras (3), Lights (5 + env sphere)")
    print(f"  Active camera: Cam_Perspective (inside detector, looking into phi-cut)")
    print(f"  Cam_Transverse: end-cap view (Y=up, Z=horizontal transverse)")
    print(f"  Cam_Side: elevation view (X=beam left-right, Y=up)")
    if not no_phi_cut:
        print(f"  Phi cutaway: [{phi_min:.0f}°, {phi_max:.0f}°]  "
              f"(live Boolean via PhiWedge cutter — adjust Phi Min/Max in modifier panel)")
    print(f"  Render: Cycles 4 K, 128 samples, OIDN denoiser")
    print(f"  Lighting: golden-hour (3000 K key) + sky fill (7500 K) + rim (4500 K)"
          f" + interior fill (warm white) + purple IP glow")

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
