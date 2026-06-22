"""
simplify_barrel.py — structure-aware simplification of a polygonal (staved)
calorimeter BARREL. The barrel is a 12-stave dodecagon; the sampling layers stack
in the local DEPTH direction (perpendicular to each flat stave face), not global
radius. For each (stave x depth-layer) cell we take the convex hull of its points,
turning each ~5.5mm layer's many thin sub-slices (W/Si/PCB/air) into one solid
tile — removing the ratty inter-slice gaps while keeping the 50-layer structure
and the cutaway. Also drops faces touching the exact origin.

Usage: python Tools/simplify_barrel.py <in.glb> <out.glb> [n_staves=12] [n_layers=50]
"""
import sys
import numpy as np
import trimesh
from trimesh.convex import convex_hull

inp, outp = sys.argv[1], sys.argv[2]
N_STAVE = int(sys.argv[3]) if len(sys.argv) > 3 else 12
N_LAYER = int(sys.argv[4]) if len(sys.argv) > 4 else 50

m = trimesh.load(inp, file_type="glb", force="mesh", process=False)
v = np.asarray(m.vertices)
f = np.asarray(m.faces)
print("IN verts=%d faces=%d bbox=%s" % (len(v), len(f), np.round(m.bounds, 1).tolist()))

# Drop origin-touching faces
oidx = np.where(np.all(v == 0.0, axis=1))[0]
bad = np.isin(f, oidx).any(axis=1)
print("origin faces removed:", int(bad.sum()))
m.update_faces(~bad)
m.remove_unreferenced_vertices()
v = np.asarray(m.vertices)

axis = int(np.argmax(v.max(0) - v.min(0)))   # beam axis (X)
o = [i for i in range(3) if i != axis]
t = v[:, o]                                   # transverse (y,z)
phi = np.arctan2(t[:, 1], t[:, 0])

# Each stave spans 360/N_STAVE; widen its angular window so adjacent stave hulls
# OVERLAP and fuse (no inter-stave cracks). Vertices may belong to >1 stave.
stave_w = 2 * np.pi / N_STAVE
STAVE_OVERLAP = np.radians(8.0)
half = stave_w / 2 + STAVE_OVERLAP

hulls = []
overlap = 0.15  # depth-bin overlap fraction to fuse adjacent layers
for k in range(N_STAVE):
    ph_k = k * stave_w
    dphi = np.arctan2(np.sin(phi - ph_k), np.cos(phi - ph_k))  # wrapped angular dist
    sm = np.abs(dphi) <= half
    if sm.sum() < 50:
        continue
    n_k = np.array([np.cos(ph_k), np.sin(ph_k)])     # outward normal in transverse plane
    tk = t[sm]
    depth = tk[:, 0] * n_k[0] + tk[:, 1] * n_k[1]    # explicit projection (avoid matmul nan)
    d0, d1 = np.percentile(depth, 0.5), np.percentile(depth, 99.5)
    if d1 - d0 < 5:
        continue
    edges = np.linspace(d0, d1, N_LAYER + 1)
    vk = v[sm]
    bw = (d1 - d0) / N_LAYER
    for li in range(N_LAYER):
        lo, hi = edges[li] - overlap * bw, edges[li + 1] + overlap * bw
        cmask = (depth >= lo) & (depth < hi)
        if cmask.sum() < 8:
            continue
        try:
            h = convex_hull(vk[cmask])
            if h.volume > 1.0:
                hulls.append(h)
        except Exception:
            pass

print("cells hulled:", len(hulls))
out = trimesh.util.concatenate(hulls)
print("OUT verts=%d faces=%d bbox=%s" % (len(out.vertices), len(out.faces), np.round(out.bounds, 1).tolist()))
out.export(outp)
print("wrote", outp)
