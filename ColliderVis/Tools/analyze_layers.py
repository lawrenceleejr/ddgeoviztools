"""Analyze the radial layer structure of a calorimeter glb (single merged mesh).
Detects the barrel/symmetry axis and histograms vertex radial distances to reveal
the repeated sampling-layer shells (e.g. ECAL barrel = 50 repeats x 8 slices)."""
import sys
import numpy as np
import trimesh

path = sys.argv[1]
m = trimesh.load(path, file_type="glb", force="mesh", process=False)
v = np.asarray(m.vertices)
f = np.asarray(m.faces)
print("FILE", path)
print("verts=%d faces=%d" % (len(v), len(f)))
print("bbox min", np.round(v.min(0), 2), "max", np.round(v.max(0), 2))
print("extent", np.round(v.max(0) - v.min(0), 2))
norigin = int(np.all(v == 0.0, axis=1).sum())
print("exact-origin verts:", norigin)

for ax, axn in [(0, "X"), (1, "Y"), (2, "Z")]:
    others = [i for i in range(3) if i != ax]
    r = np.sqrt(v[:, others[0]] ** 2 + v[:, others[1]] ** 2)
    hist, edges = np.histogram(r, bins=120)
    nz = hist > 0
    bands = int(np.sum(nz[1:] & ~nz[:-1]) + (1 if nz[0] else 0))
    # extent along this axis
    print("\naxis %s : r[min,max]=[%.1f, %.1f]  along-axis extent=%.1f  ~bands(120bin)=%d"
          % (axn, r.min(), r.max(), v[:, ax].max() - v[:, ax].min(), bands))

# Pick the axis whose along-axis extent is the *longest* (beam axis for a barrel)
ext = v.max(0) - v.min(0)
axis = int(np.argmax(ext))
others = [i for i in range(3) if i != axis]
r = np.sqrt(v[:, others[0]] ** 2 + v[:, others[1]] ** 2)
print("\nCHOSEN AXIS =", "XYZ"[axis], "(longest extent). Radial shell analysis:")
# Fine histogram to locate shells
rs = np.sort(r)
# unique radii rounded to 0.5 mm
rr = np.round(r, 1)
uniq, counts = np.unique(rr, return_counts=True)
# report only well-populated radii (shell surfaces)
big = uniq[counts > max(5, counts.max() * 0.02)]
print("populated radii count:", len(big))
if len(big):
    print("min shell r=%.1f  max shell r=%.1f" % (big.min(), big.max()))
    # gaps between consecutive populated radii -> layer spacing
    d = np.diff(np.sort(big))
    print("first 40 populated radii:", np.round(np.sort(big)[:40], 1))
    print("typical spacing (median diff)=%.2f" % (np.median(d) if len(d) else 0))
