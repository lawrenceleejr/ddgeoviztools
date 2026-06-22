"""
simplify_calo.py — structure-aware calorimeter simplification (NO general decimation).

For a calorimeter glb (single merged mesh) this:
  1. Removes faces touching the EXACT detector origin (0,0,0) — the incorrect faces.
  2. Detects the repeated sampling-layer structure and replaces each repeat unit
     (one ~5.5mm layer = the "8 slices") with the CONVEX HULL of that unit, per
     angular sector, so the ratty inter-slice gaps become solid layer tiles while
     the overall shape + the cutaway are preserved.

Barrel mode: layers are RADIAL shells about the long axis; cells = (radial layer x
phi sector), hull spans the full length. Endcap mode: layers stack ALONG the axis;
cells = (axial layer x phi sector x radial ring).

Usage:
  python Tools/simplify_calo.py <in.glb> <out.glb> <mode barrel|endcap> [n_layers] [n_phi] [n_radial_rings]
"""
import sys
import numpy as np
import trimesh
from trimesh.convex import convex_hull

inp, outp, mode = sys.argv[1], sys.argv[2], sys.argv[3]
N_LAYERS = int(sys.argv[4]) if len(sys.argv) > 4 else 50
N_PHI = int(sys.argv[5]) if len(sys.argv) > 5 else 120
N_RING = int(sys.argv[6]) if len(sys.argv) > 6 else 6  # endcap radial rings

m = trimesh.load(inp, file_type="glb", force="mesh", process=False)
v = np.asarray(m.vertices)
f = np.asarray(m.faces)
print("IN  verts=%d faces=%d bbox=%s" % (len(v), len(f), np.round(m.bounds, 1).tolist()))

# 1) Drop faces with a vertex at the exact origin.
origin_idx = np.where(np.all(v == 0.0, axis=1))[0]
bad = np.isin(f, origin_idx).any(axis=1)
print("origin verts=%d  faces touching origin removed=%d" % (len(origin_idx), int(bad.sum())))
m.update_faces(~bad)
m.remove_unreferenced_vertices()
v = np.asarray(m.vertices)

# Axis = longest extent.
ext = v.max(0) - v.min(0)
axis = int(np.argmax(ext))
o = [i for i in range(3) if i != axis]
r = np.sqrt(v[:, o[0]] ** 2 + v[:, o[1]] ** 2)
phi = np.arctan2(v[:, o[1]], v[:, o[0]])  # -pi..pi
ax = v[:, axis]

PHI_OVERLAP = (2 * np.pi / N_PHI) * 0.18  # slight overlap so adjacent hulls fuse
hulls = []


def add_cell(mask):
    pts = v[mask]
    if len(pts) < 8:
        return
    # reject near-degenerate (all collinear/coplanar handled by QHull failure)
    try:
        h = convex_hull(pts)
        if h.volume > 1.0:  # mm^3, skip slivers
            hulls.append(h)
    except Exception:
        pass


if mode == "barrel":
    r0, r1 = np.percentile(r, 0.5), np.percentile(r, 99.5)
    edges = np.linspace(r0, r1, N_LAYERS + 1)
    for li in range(N_LAYERS):
        lo, hi = edges[li], edges[li + 1]
        rmask = (r >= lo - 0.2) & (r < hi + 0.2)
        if not rmask.any():
            continue
        for si in range(N_PHI):
            p0 = -np.pi + si * (2 * np.pi / N_PHI)
            p1 = p0 + (2 * np.pi / N_PHI)
            pmask = (phi >= p0 - PHI_OVERLAP) & (phi < p1 + PHI_OVERLAP)
            add_cell(rmask & pmask)
else:  # endcap: layers along axis
    a0, a1 = np.percentile(ax, 0.5), np.percentile(ax, 99.5)
    edges = np.linspace(a0, a1, N_LAYERS + 1)
    r0, r1 = np.percentile(r, 0.5), np.percentile(r, 99.5)
    redges = np.linspace(r0, r1, N_RING + 1)
    for li in range(N_LAYERS):
        lo, hi = edges[li], edges[li + 1]
        amask = (ax >= lo - 0.2) & (ax < hi + 0.2)
        if not amask.any():
            continue
        for ri in range(N_RING):
            rmask = (r >= redges[ri]) & (r < redges[ri + 1])
            for si in range(N_PHI):
                p0 = -np.pi + si * (2 * np.pi / N_PHI)
                p1 = p0 + (2 * np.pi / N_PHI)
                pmask = (phi >= p0 - PHI_OVERLAP) & (phi < p1 + PHI_OVERLAP)
                add_cell(amask & rmask & pmask)

print("cells hulled:", len(hulls))
out = trimesh.util.concatenate(hulls)
print("OUT verts=%d faces=%d bbox=%s" % (len(out.vertices), len(out.faces), np.round(out.bounds, 1).tolist()))
out.export(outp)
print("wrote", outp)
