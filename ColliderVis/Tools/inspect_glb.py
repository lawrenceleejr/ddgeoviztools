"""Dump glTF/GLB structure: meshes, primitives, material names, node tree, and
per-primitive bounds — to understand how the calorimeter slice/layer repeats are
represented before any structure-aware simplification."""
import sys
import struct
import numpy as np
from pygltflib import GLTF2

path = sys.argv[1]
g = GLTF2().load_binary(path)

print("=" * 70)
print("FILE:", path)
print("meshes=%d  materials=%d  nodes=%d  accessors=%d  bufferViews=%d"
      % (len(g.meshes or []), len(g.materials or []), len(g.nodes or []),
         len(g.accessors or []), len(g.bufferViews or [])))

print("\n--- MATERIALS ---")
for i, m in enumerate(g.materials or []):
    print("  mat[%2d] name=%r" % (i, m.name))

print("\n--- MESHES (name, #prims, material idx per prim) ---")
for i, m in enumerate(g.meshes or []):
    mats = [p.material for p in m.primitives]
    # collapse runs for readability
    print("  mesh[%2d] name=%r prims=%d matIdx(first 24)=%s"
          % (i, m.name, len(m.primitives), mats[:24]))

print("\n--- NODES (name : mesh idx) first 80 ---")
nodes = g.nodes or []
for i, n in enumerate(nodes[:80]):
    print("  node[%3d] name=%r mesh=%s children=%s"
          % (i, n.name, n.mesh, (n.children[:6] if n.children else None)))
print("  ... total nodes =", len(nodes))

# Material name histogram (slice material pattern)
from collections import Counter
matnames = [ (m.name or "") for m in (g.materials or []) ]
print("\n--- MATERIAL NAME HISTOGRAM ---")
for name, c in Counter(matnames).most_common():
    print("  %4d  %r" % (c, name))
