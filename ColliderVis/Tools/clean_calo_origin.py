"""Remove faces touching the EXACT origin (0,0,0) from all four calorimeter glbs.
Reads each mesh's pristine original (.glb.orig if present, else backs up .glb -> .glb.orig
first), removes only origin-touching faces via trimesh (correct topology), exports back
to the working .glb. No decimation, no other changes."""
import shutil
from pathlib import Path
import numpy as np
import trimesh

MESHDIR = Path("/Users/leejr/Work/ddgeoviztools/ColliderVis/ue5_meshes")
NAMES = ["ECalBarrel", "HCalBarrel", "ECalEndcap", "HCalEndcap"]

for name in NAMES:
    glb = MESHDIR / f"{name}.glb"
    orig = MESHDIR / f"{name}.glb.orig"
    if not orig.is_file():
        shutil.copy2(glb, orig)
        print(f"{name}: backed up -> {orig.name}")
    scene = trimesh.load(str(orig), file_type="glb", force="scene", process=False)
    gname, m = list(scene.geometry.items())[0]
    v = np.asarray(m.vertices)
    f = np.asarray(m.faces)
    oidx = np.where(np.all(v == 0.0, axis=1))[0]
    bad = np.isin(f, oidx).any(axis=1)
    n = int(bad.sum())
    b0 = m.bounds.copy()
    m.update_faces(~bad)
    m.remove_unreferenced_vertices()
    bd = float(np.abs(m.bounds - b0).max())
    scene.export(str(glb))
    chk = trimesh.load(str(glb), file_type="glb", force="mesh", process=False)
    cv = np.asarray(chk.vertices)
    left = int(np.all(cv == 0.0, axis=1).sum())
    print(f"{name}: origin_verts={len(oidx)} removed_faces={n} faces {len(f)}->{len(chk.faces)} "
          f"bounds_delta={bd:.4f} origin_left={left}")
