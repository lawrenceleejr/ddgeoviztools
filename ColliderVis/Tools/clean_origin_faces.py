"""
clean_origin_faces.py — from the SESSION-START originals (*.glb.orig), remove ONLY
the triangles that have a vertex at the exact origin (0,0,0), using trimesh's
well-tested face-mask removal + glb re-export (correct indices/topology — unlike the
earlier hand-edited index buffers that came out raggedy).

Run with the meshfix venv:
    /Users/leejr/Work/ddgeoviztools/ColliderVis/.venv_meshfix/bin/python \
        /Users/leejr/Work/ddgeoviztools/ColliderVis/Tools/clean_origin_faces.py
"""
import numpy as np
import trimesh
from pathlib import Path

MESHDIR = Path("/Users/leejr/Work/ddgeoviztools/ColliderVis/ue5_meshes")
TARGETS = ["ECalBarrel", "HCalBarrel"]

for name in TARGETS:
    orig = MESHDIR / f"{name}.glb.orig"
    out = MESHDIR / f"{name}.glb"
    if not orig.is_file():
        print(f"!! {name}: missing original {orig}")
        continue

    # Load preserving structure; don't let trimesh merge/alter the mesh.
    # (.orig extension would confuse the loader, so force the glb reader.)
    scene = trimesh.load(str(orig), file_type="glb", force="scene", process=False)
    geoms = list(scene.geometry.items())
    if len(geoms) != 1:
        print(f"!! {name}: expected 1 geometry, got {len(geoms)} — skipping")
        continue
    gname, m = geoms[0]

    v = np.asarray(m.vertices)
    f = np.asarray(m.faces)
    bounds_before = m.bounds.copy()

    # Exact-origin vertices and the faces that reference them.
    origin_vert = np.all(v == 0.0, axis=1)
    origin_idx = np.where(origin_vert)[0]
    bad_face = np.isin(f, origin_idx).any(axis=1)
    keep = ~bad_face
    removed = int(bad_face.sum())

    print(f"{name}: verts={len(v)} faces={len(f)} origin_verts={len(origin_idx)} "
          f"bad_faces={removed}")

    # Safety: refuse to gut the mesh.
    if removed > len(f) * 0.01:
        print(f"!! {name}: would remove {removed} faces (> 1%) — ABORT, not writing")
        continue

    m.update_faces(keep)
    m.remove_unreferenced_vertices()

    bounds_after = m.bounds
    bdelta = float(np.abs(bounds_after - bounds_before).max())

    scene.export(str(out))

    # Verify reload.
    chk = trimesh.load(str(out), force="scene", process=False)
    cg = list(chk.geometry.values())[0]
    cv = np.asarray(cg.vertices)
    still_origin = int(np.all(cv == 0.0, axis=1).sum())
    print(f"{name}: -> wrote {out.name}  faces {len(f)}->{len(cg.faces)} "
          f"verts {len(v)}->{len(cv)}  bounds_delta={bdelta:.4f}  "
          f"origin_verts_left={still_origin}")
