"""
Create a Blender scene (.blend) from per-sub-detector mesh files.

Features
--------
- Reads OBJ / GLTF / VTP mesh files produced by ddgeoviztools' convert step.
- Cleans up duplicate vertices (trimesh process=True + Weld modifier).
- Assigns physics-inspired materials (steel, brass, copper, matte variants).
- Applies a phi-cutaway via bmesh bisect (creates new vertices at the exact
  intersection of existing edges with the phi boundary planes, producing
  geometrically clean, razor-sharp cut edges baked into the mesh).
- Sets up the scene with GDML geometry imported then rotated +90° around Y
  so that the GDML beam axis (Z) maps to Blender's X axis.  Objects are
  kept at native GDML mm scale (1 BU = 1 mm).
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
    # Anisotropic brushed-metal look: elongated highlights mimic machined surfaces.
    # Only apply to metallic materials (metallic > 0.3).
    if metallic > 0.3:
        for key in ("Anisotropic", "Anisotropy"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = 0.35
                break
        for key in ("Anisotropic Rotation", "Anisotropy Rotation"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = 0.0
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

    Uses the bespoke ``_slice_mesh_plane_np`` slicer which classifies vertices
    within eps=1e-3 mm of the cut plane as "on-plane" (positive side) to avoid
    the index=-1 wild-polygon bug that trimesh's slice_faces_plane can produce
    when a mesh vertex sits exactly on the cut boundary.  The strategy is:

      1. LEFT  = keep phi < phi_min  (positive side of normal_out_min)
      2. INNER = keep phi ≥ phi_min  (positive side of −normal_out_min)
      3. RIGHT = INNER ∩ phi > phi_max
      4. Combine LEFT + RIGHT

    A centroid-based sanity pass is run at the end to drop any stray faces
    that numerically survived near the cut planes.

    Returns (new_vertices, new_faces).
    """
    phi_min = math.radians(phi_min_deg)
    phi_max = math.radians(phi_max_deg)
    origin  = np.zeros(3)

    # Normal at phi_min pointing AWAY from sector (toward phi < phi_min)
    normal_out_min = np.array([math.cos(phi_min), math.sin(phi_min), 0.0])
    # Normal at phi_max pointing AWAY from sector (toward phi > phi_max)
    normal_out_max = np.array([-math.cos(phi_max), -math.sin(phi_max), 0.0])

    def _slice(verts, faces_, normal):
        """Slice keeping the positive-normal side; returns (verts, faces).

        Uses _slice_mesh_plane_np which treats vertices within eps=1e-3 mm of
        the plane as on-plane (positive side).  This prevents the index=-1
        wild-polygon bug: without the guard, a straddle face with one on-plane
        vertex has only ONE crossing edge instead of two; the missing
        intersection index is -1 which numpy silently maps to the last vertex,
        producing triangles that shoot off to an arbitrary point in the mesh.
        """
        if len(faces_) == 0:
            return verts, faces_
        return _slice_mesh_plane_np(verts, faces_, origin, normal)

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

    verts = raw.vertices.tolist()   # list of [x, y, z]
    faces = raw.faces.tolist()      # list of [i, j, k]

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    # Shade smooth — mesh.shade_smooth() is the Blender 4.1+ API.
    # In Blender 5.0 the per-face 'use_smooth' flag was removed from the
    # internal mesh representation; foreach_set("use_smooth", …) writes to a
    # legacy shim and can corrupt the CustomData layer table in a way that
    # causes save_as_mainfile to crash with SIGSEGV.  Use shade_smooth() when
    # available, otherwise skip smooth shading rather than risk corruption.
    try:
        me.shade_smooth()
    except AttributeError:
        pass   # Blender < 4.1 fallback: flat shading acceptable for vis
    me.update()
    # Clean any degenerate / out-of-range mesh data before handing the mesh
    # to Blender's modifier stack and serialiser.
    me.validate(verbose=False, clean_customdata=True)

    obj = bpy.data.objects.new(name, me)
    bpy.data.scenes[0].collection.objects.link(obj)

    # Phi-sector cutaway using bmesh bisect — definitively creates new vertices
    # at the exact intersection of mesh edges with each cut plane, then deletes
    # faces inside the sector.  This avoids the LEFT+RIGHT numpy combination
    # which caused massive vertex duplication → degenerate faces → Solidify
    # wild rim polygons on the open holes.
    if phi_min_deg is not None and phi_max_deg is not None:
        _apply_phi_cutaway_bmesh(obj, phi_min_deg, phi_max_deg)

        # For solid meshes, cap the open boundary loops left by the bisect cut.
        if solid:
            try:
                _cap_boundary_loops_bmesh(obj)
                print(f"    [SOLID] Boundaries capped → "
                      f"{len(obj.data.polygons):,} faces", flush=True)
            except Exception as exc:
                print(f"    [SOLID] Boundary cap failed ({exc})", flush=True)

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
    mod.use_even_offset   = True          # uniform thickness on sloped faces
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

def _cap_boundary_loops_bmesh(obj):
    """
    Fill open boundary loops on a bpy object using bmesh triangle_fill.

    After a phi-sector bisect cut, the mesh has open boundary edges along each
    cut plane.  This fills those loops with triangles so the cross-section
    appears solid.
    """
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    boundary_edges = [e for e in bm.edges if e.is_boundary]
    if boundary_edges:
        bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=True,
                                edges=boundary_edges)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


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
    removing the sector and revealing the interior.

    The wedge is built directly in Blender WORLD coordinates (NOT in GDML local
    coordinates) so that NO rotation needs to be applied to it.  Detector objects
    have Ry(+90°) applied, which means their world-space phi is:
        phi = atan2(Z_world, Y_world)
        phi=0°  → +Y_world direction
        phi=90° → +Z_world direction

    The wedge geometry matches this exactly:
        center axis along ±X_world (beam direction)
        arc: y = r·cos(ang), z = r·sin(ang)  in Y_world-Z_world plane
        → world phi = atan2(z, y) = ang  ✓

    The wedge is a closed, manifold solid (required for Blender Boolean).
    It is hidden in the viewport and renders.
    """
    import bmesh as _bm

    N_ARC  = 64           # arc segments within the sector
    r      = radius
    half_d = depth / 2.0

    phi_min_r = math.radians(phi_min_deg)
    phi_max_r = math.radians(phi_max_deg)

    me = bpy.data.meshes.new("PhiWedge")
    bm = _bm.new()

    # Centre vertices on the ±X_world caps (beam axis in world space)
    vc_pos = bm.verts.new((+half_d, 0.0, 0.0))
    vc_neg = bm.verts.new((-half_d, 0.0, 0.0))

    # Arc vertices at ±X_world from phi_min to phi_max (N_ARC+1 vertices inclusive)
    # World-space phi = atan2(Z_world, Y_world): phi=0 → +Y_world, phi=90° → +Z_world
    vp, vn = [], []
    for i in range(N_ARC + 1):
        ang = phi_min_r + i * (phi_max_r - phi_min_r) / N_ARC
        y   = r * math.cos(ang)   # Y_world component
        z   = r * math.sin(ang)   # Z_world component
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

    Tries, in order:
      1. light_data.use_color_temperature + light_data.temperature  (Blender 4.4+)
      2. ShaderNodeBlackbody in the light's node tree  (Blender 3.x / 4.x)
      3. _kelvin_to_rgb RGB fallback (last resort)
    """
    # --- Attempt 1: native use_color_temperature (Blender 4.4+) ---
    # Blender 4.4 introduced a dedicated color-temperature property on lights.
    # When enabled, the light colour is computed from a true Planck blackbody
    # spectrum rather than a user-supplied RGB.
    if hasattr(light_data, "use_color_temperature"):
        try:
            light_data.use_color_temperature = True
            light_data.temperature = float(temp_kelvin)
            print(f"  [LIGHT] {name}  {energy:.0f} W  "
                  f"{temp_kelvin:.0f} K  (native use_color_temperature)",
                  flush=True)
            return
        except Exception as exc:
            print(f"  [LIGHT] {name}  use_color_temperature failed: {exc}",
                  flush=True)

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

    spot_energy = energy_base * 2000.0   # strong spot to produce visible scattering
    light_data        = bpy.data.lights.new(name, type="SPOT")
    light_data.energy = spot_energy
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

    # Render-only: hidden from viewport so it doesn't clutter editing
    light_obj.hide_viewport = True
    light_obj.hide_render   = False

    print(f"  [GODRAYS] Spot light '{name}'  phi={phi_center_deg:.1f}°  "
          f"energy={spot_energy:.0f} W  (render-only)", flush=True)
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

    # Set Cycles to GPU rendering so the .blend renders on a workstation GPU.
    # In Blender 5.0+, setting GPU on a headless build without hardware triggers
    # CUEW/HIP/Metal enumeration that can leave Cycles in an invalid state and
    # crash save_as_mainfile.  Skip the device override on 5.0+; the user can
    # select the render device when opening the file on their workstation.
    if bpy.app.version < (5, 0, 0):
        scene.cycles.device = "GPU"
        print("  [RENDER] Cycles device set to GPU", flush=True)
    else:
        print("  [RENDER] Cycles device: not set (Blender 5.0+ — select on workstation)", flush=True)

    # Resolution — 4 K UHD
    scene.render.resolution_x          = 3840
    scene.render.resolution_y          = 2160
    scene.render.resolution_percentage = 100

    # Cycles samples and denoising.
    # In Blender 5.0+, setting use_denoising=True or denoiser="OPENIMAGEDENOISE"
    # can trigger the OIDN plugin loader.  On a headless build where the OIDN
    # shared library is not present this leaves a dangling plugin reference that
    # crashes save_as_mainfile with SIGSEGV.  Skip on 5.0+; the user can enable
    # denoising after opening the file on their rendering workstation.
    # Volume settings are also skipped: the volume sphere is already excluded on
    # 5.0+ so there is no reason to touch Cycles volume transport settings.
    if bpy.app.version < (5, 0, 0):
        scene.cycles.samples        = 128
        scene.cycles.use_denoising  = True
        try:
            scene.cycles.denoiser = "OPENIMAGEDENOISE"
        except Exception:
            pass
        try:
            scene.cycles.volume_bounces    = 4
            scene.cycles.volume_step_rate  = 1.0
            scene.cycles.volume_max_steps  = 256
            print(f"  [RENDER] Volume bounces: {scene.cycles.volume_bounces}  "
                  f"step_rate: {scene.cycles.volume_step_rate}  "
                  f"max_steps: {scene.cycles.volume_max_steps}", flush=True)
        except (AttributeError, TypeError) as exc:
            print(f"  [RENDER] Volume settings not available: {exc}", flush=True)
    else:
        try:
            scene.cycles.samples = 128
        except Exception:
            pass
        print("  [RENDER] Cycles: samples=128  "
              "(denoising/volume skipped on Blender 5.0+ headless)", flush=True)

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

    # Exposure: +4 EV lifts the render by 16× which is needed because at
    # native mm scale the lights are physically far from the detector
    # surfaces and Cycles inverse-square falloff makes the base illumination
    # very dim.
    try:
        scene.view_settings.exposure = 4.0
    except Exception:
        pass

    # Contrast look — try AgX-style names first, then Filmic
    for look in ("Medium Contrast", "AgX - Medium Contrast",
                 "Medium High Contrast", "Base Contrast"):
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
    _setup_world()

    # ---- Pre-create materials ----
    print(f"  [SETUP] Pre-creating materials ...", flush=True)
    materials = _pre_create_materials()
    mat_cycle = cycle(materials)
    print(f"  [SETUP] {len(materials)} materials ready: "
          f"{[m.name for m in materials]}", flush=True)

    # ---- Load each mesh ----
    # Meshes are loaded INTACT (no phi cut at load time).  The phi cutaway is
    # applied later via a Boolean DIFFERENCE modifier (wedge cutter) that runs
    # AFTER the Solidify modifier in the stack.  This ordering is critical:
    #   Weld → Solidify (intact closed mesh → solid shell) → Boolean DIFFERENCE
    # If the phi cut were applied at load time, Solidify would see open boundary
    # edges at the cut planes and span them with giant rim faces → wild polygons.
    if not no_phi_cut:
        print(f"  [PHI] Phi cutaway [{phi_min:.1f}°, {phi_max:.1f}°] will be applied "
              f"via Boolean DIFFERENCE modifier after Solidify.", flush=True)

    loaded_objects: list = []
    for mesh_path in mesh_files:
        name = mesh_path.stem
        print(f"  Loading {mesh_path.name} ...")
        # Nozzles are filled to a solid convex hull so the cutaway cross-section
        # appears as solid material (Boolean handles the cut cleanly on manifold).
        _is_nozzle = "Nozzle" in name
        try:
            obj = _load_mesh(mesh_path, name,
                             phi_min_deg=None,
                             phi_max_deg=None,
                             solid=_is_nozzle)
        except Exception as exc:
            print(f"  [WARN] Could not load {mesh_path.name}: {exc}", file=sys.stderr)
            continue

        # Material — try to infer from the sub-detector name, else cycle palette
        mat = _material_for_detector(name, mat_cycle)
        obj.data.materials.append(mat)

        # Weld only — Solidify is intentionally omitted.  Solidify on an
        # open shell creates rim faces that span the phi-cut opening and
        # produce wild polygons; the Boolean DIFFERENCE below handles the
        # clean cutaway without needing a thickened shell.
        _add_weld(obj, threshold=weld_threshold)

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

    # ---- Phi-cutaway (Boolean DIFFERENCE modifier) ----
    # Meshes are loaded intact.  The phi cut is done here by a Boolean DIFFERENCE
    # modifier (wedge cutter) that sits AFTER Solidify in the modifier stack:
    #   Weld → Solidify → Boolean DIFFERENCE → Bevel
    # Solidify sees the intact closed mesh and produces a proper solid shell.
    # Boolean then cuts the solid — clean intersection vertices, no open edges.
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
            # No rotation on the wedge — it is built directly in world-space
            # coordinates: center axis along X_world (beam), arc in Y_world-Z_world.
            # Detector objects have Ry(+90°) applied, which transforms their GDML
            # vertices so that phi = atan2(Z_world, Y_world).  The wedge arc uses
            # y=r*cos(ang), z=r*sin(ang) in local space, which without any rotation
            # gives world-space phi = atan2(Z,Y) = ang.  Applying Ry(+90°) to the
            # wedge would rotate the arc into the X_world-Y_world plane, covering
            # the wrong angular sector entirely.

            for obj in loaded_objects:
                mod = obj.modifiers.new("PhiBoolean", "BOOLEAN")
                mod.operation = "DIFFERENCE"
                mod.object = wedge_obj
                # Exact solver: most robust for complex/non-manifold detector
                # geometry.  FLOAT/FAST are less precise and produce "Using
                # fallback" warnings on thin shells.
                try:
                    mod.solver = "EXACT"
                except TypeError:
                    pass  # Older Blender without Exact solver
                # Hole Tolerant: required for open-shell (non-manifold) meshes
                # to get a correct Boolean result without artifacts.
                try:
                    mod.use_hole_tolerant = True
                except AttributeError:
                    pass  # Not available in all Blender versions
                # Self Intersection: needed for detector geometry that has
                # self-intersecting faces (common in complex GDML exports).
                try:
                    mod.use_self = True
                except AttributeError:
                    pass  # Not available in all Blender versions
                mod.show_viewport = True
                mod.show_render = True
            print(f"  [PHI] Boolean DIFFERENCE modifier added and ENABLED on "
                  f"{len(loaded_objects)} objects.", flush=True)
        except Exception as exc:
            print(f"  [PHI] Boolean wedge creation failed: {exc}",
                  flush=True)

    # --- Bevel modifier (after phi-cutaway so it bevels the cut edges too) ---
    if not no_bevel:
        for obj in loaded_objects:
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
    # Objects are at native GDML mm scale: r is ~2000–6000 BU (= mm).
    # Cycles uses physical inverse-square falloff: irradiance = Power / (4π d²)
    # where d is in Blender units (= mm here).  With scale_length = 0.001,
    # Blender converts BU → metres for the falloff calculation, so a light
    # at 5000 mm = 5 m needs proportionally high wattage.
    # energy_base scales with r² so that relative brightness is constant
    # regardless of detector size.
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
        color_rgb=(1.0, 0.97, 0.92),   # fallback if temperature fails
        soft_size=r * 0.50,
        temp_kelvin=4000.0,             # warm white via true blackbody
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
    # Blender 5.0+ crashes in save_as_mainfile with any Volume material node
    # tree (VolumeScatter, VolumePrincipled) — skip entirely on 5.0+.
    _phi_center_deg = (phi_min + phi_max) / 2.0 if not no_phi_cut else 45.0
    if bpy.app.version < (5, 0, 0):
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
    else:
        print("  [INFO] God ray volume sphere skipped (Blender 5.0+ volume materials crash on save).",
              flush=True)

    # ---- Render settings + compositor bloom ----
    print(f"  [SETUP] Configuring render settings ...", flush=True)
    scene = bpy.data.scenes[0]
    _setup_render_and_compositor(scene)
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
          f"Cameras (3), Lights (5 + env sphere)")
    print(f"  Active camera: Cam_Perspective (inside detector, looking into phi-cut)")
    print(f"  Cam_Transverse: end-cap view (Y=up, Z=horizontal transverse)")
    print(f"  Cam_Side: elevation view (X=beam left-right, Y=up)")
    if not no_phi_cut:
        print(f"  Phi cutaway: [{phi_min:.0f}°, {phi_max:.0f}°] removed  "
              f"(bmesh bisect — clean intersection edges baked into mesh)")
        print(f"  PhiBoolean (DIFFERENCE): disabled by default — enable per-object "
              f"if mesh is manifold")
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
