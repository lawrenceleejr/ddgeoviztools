// build-models.mjs — turn the VTK-exported sub-detector GLTFs in
// ../data/output/ into web-ready parts.
//
//   node scripts/build-models.mjs [--in ../data/output] [--out public/models]
//
// For every <System>.gltf:
//   1. keep only TRIANGLES primitives (VTK also emits POINTS / LINES);
//   2. split each primitive into named parts (staves, ±z endcap halves,
//      tracker layers / disks) using the geometry itself;
//   3. unweld, drop VTK vertex colours (normals come from flatShading at runtime);
//   4. weld, quantise (KHR_mesh_quantization), meshopt-compress
//      (EXT_meshopt_compression) and write <System>.glb;
//   5. append every part to parts.json (bbox, radial / z midpoints, role).
//
// Coordinates are GDML mm with Z along the beam and Y up.

import { readdirSync, mkdirSync, writeFileSync, statSync } from 'node:fs';
import { resolve, basename } from 'node:path';
import { Document, NodeIO, Primitive } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { weld, quantize, meshopt, prune } from '@gltf-transform/functions';
import { MeshoptEncoder, MeshoptDecoder } from 'meshoptimizer';

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, arr) => {
    if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1]]);
    return acc;
  }, []),
);
const IN = resolve(args.in ?? '../data/output');
const OUT = resolve(args.out ?? 'public/models');
mkdirSync(OUT, { recursive: true });

// Material key per system (palette lives in src/palette.js at runtime and in
// src/gdml_to_blender.py for Blender; we only need the key here).
function groupOf(system) {
  const s = system.toLowerCase();
  if (s.startsWith('ecal')) return 'ecal';
  if (s.startsWith('hcal')) return 'hcal';
  if (s.startsWith('yoke')) return 'yoke';
  if (s.includes('bch')) return 'bch';
  if (s.startsWith('nozzle')) return 'nozzle';
  if (s === 'solenoid') return 'solenoid';
  if (s === 'vertex') return 'vertex';
  if (s.includes('tracker')) return 'tracker';
  if (s === 'beampipe') return 'beampipe';
  return 'other';
}

await MeshoptEncoder.ready;
await MeshoptDecoder.ready;
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ 'meshopt.encoder': MeshoptEncoder, 'meshopt.decoder': MeshoptDecoder });

// ---------- geometry helpers (plain typed arrays) ----------

/** Expand an indexed primitive into a flat list of triangles [x0,y0,z0, x1,...]. */
function triangles(prim) {
  const pos = prim.getAttribute('POSITION').getArray();
  const idx = prim.getIndices()?.getArray();
  const n = idx ? idx.length : pos.length / 3;
  const out = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const v = idx ? idx[i] : i;
    out[i * 3] = pos[v * 3];
    out[i * 3 + 1] = pos[v * 3 + 1];
    out[i * 3 + 2] = pos[v * 3 + 2];
  }
  return out; // 9 floats per triangle
}

function triCount(tris) {
  return tris.length / 9;
}

/** Select triangles by predicate on (cx, cy, cz) centroid. */
function filterTris(tris, pred) {
  const keep = [];
  for (let t = 0; t < triCount(tris); t++) {
    const o = t * 9;
    const cx = (tris[o] + tris[o + 3] + tris[o + 6]) / 3;
    const cy = (tris[o + 1] + tris[o + 4] + tris[o + 7]) / 3;
    const cz = (tris[o + 2] + tris[o + 5] + tris[o + 8]) / 3;
    if (pred(cx, cy, cz)) keep.push(t);
  }
  const out = new Float32Array(keep.length * 9);
  keep.forEach((t, i) => out.set(tris.subarray(t * 9, t * 9 + 9), i * 9));
  return out;
}

function bounds(tris) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  let rMin = Infinity;
  let rMax = 0;
  for (let i = 0; i < tris.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], tris[i + k]);
      max[k] = Math.max(max[k], tris[i + k]);
    }
    const r = Math.hypot(tris[i], tris[i + 1]);
    rMin = Math.min(rMin, r);
    rMax = Math.max(rMax, r);
  }
  return { min, max, rMin, rMax };
}

function centroid(tris) {
  let x = 0;
  let y = 0;
  let z = 0;
  const n = tris.length / 3;
  for (let i = 0; i < tris.length; i += 3) {
    x += tris[i];
    y += tris[i + 1];
    z += tris[i + 2];
  }
  return [x / n, y / n, z / n];
}

/** Does the primitive have a z-gap around the origin (i.e. is it two endcaps)? */
function isTwoSided(tris, gap = 200) {
  let pos = 0;
  let neg = 0;
  let mid = 0;
  for (let o = 0; o < tris.length; o += 9) {
    const cz = (tris[o + 2] + tris[o + 5] + tris[o + 8]) / 3;
    if (Math.abs(cz) < gap) mid++;
    else if (cz > 0) pos++;
    else neg++;
  }
  return mid === 0 && pos > 0 && neg > 0;
}

/** Split a triangle list into clusters separated by radial gaps > `gap` mm. */
function radialClusters(tris, gap) {
  const n = triCount(tris);
  const r = new Float32Array(n);
  for (let t = 0; t < n; t++) {
    const o = t * 9;
    const cx = (tris[o] + tris[o + 3] + tris[o + 6]) / 3;
    const cy = (tris[o + 1] + tris[o + 4] + tris[o + 7]) / 3;
    r[t] = Math.hypot(cx, cy);
  }
  const order = Array.from(r.keys()).sort((a, b) => r[a] - r[b]);
  const clusters = [];
  let cur = [];
  for (let i = 0; i < order.length; i++) {
    if (cur.length && r[order[i]] - r[order[i - 1]] > gap) {
      clusters.push(cur);
      cur = [];
    }
    cur.push(order[i]);
  }
  if (cur.length) clusters.push(cur);
  return clusters.map((ids) => {
    const out = new Float32Array(ids.length * 9);
    ids.forEach((t, i) => out.set(tris.subarray(t * 9, t * 9 + 9), i * 9));
    return out;
  });
}

// ---------- part classification ----------

/**
 * Split one system's triangle primitives into named parts.
 * Returns [{ role, sign, tris }].
 */
function classify(system, prims) {
  const parts = [];
  const push = (role, sign, tris) => tris.length && parts.push({ role, sign, tris });

  if (/^(ECal|HCal|Yoke)Barrel$/.test(system)) {
    // 12 staves; name by azimuth of centroid, 0 = +x, counter-clockwise.
    const staves = prims
      .map((tris) => {
        const [cx, cy] = centroid(tris);
        const phi = ((Math.atan2(cy, cx) * 180) / Math.PI + 360) % 360;
        return { tris, phi };
      })
      .sort((a, b) => a.phi - b.phi);
    staves.forEach((s, i) => push(`stave${String(i).padStart(2, '0')}`, 0, s.tris));
    return parts;
  }

  if (/Endcap$/.test(system)) {
    for (const tris of prims) {
      const [, , cz] = centroid(tris);
      push(cz >= 0 ? 'pz' : 'nz', Math.sign(cz) || 1, tris);
    }
    return parts;
  }

  if (/Tracker|Vertex/.test(system)) {
    // Two-sided primitives with a z-gap are disk sets (split by sign).
    // Primitives that straddle z = 0 are clustered by triangle radius: each
    // radial cluster is a barrel layer, unless it is a smooth service tube
    // (≤ 1.5 mm thick, few triangles) or a thick support volume.
    const layers = [];
    const gap = Math.max(8, 0.03 * Math.max(...prims.map((t) => bounds(t).rMax)));
    for (const tris of prims) {
      if (isTwoSided(tris)) {
        push('disks', 1, filterTris(tris, (x, y, z) => z > 0));
        push('disks', -1, filterTris(tris, (x, y, z) => z <= 0));
        continue;
      }
      for (const cl of radialClusters(tris, gap)) {
        const b = bounds(cl);
        const thick = b.rMax - b.rMin;
        if (thick > 0.2 * b.rMax) push('support', 0, cl);
        else if (/Tracker/.test(system) && thick <= 1.5 && triCount(cl) <= 4096) push('shell', 0, cl);
        else layers.push({ tris: cl, r: (b.rMin + b.rMax) / 2 });
      }
    }
    layers.sort((a, b) => a.r - b.r);
    layers.forEach((l, i) => push(`layer${i}`, 0, l.tris));
    return parts;
  }

  // Everything else (Beampipe, Solenoid, Nozzle*): one part per primitive.
  prims.forEach((tris, i) => {
    const [, , cz] = centroid(tris);
    const sign = Math.abs(cz) > 100 ? Math.sign(cz) : 0;
    push(prims.length === 1 ? 'body' : `body${i}`, sign, tris);
  });
  return parts;
}

// ---------- main ----------

const files = readdirSync(IN).filter((f) => f.endsWith('.gltf')).sort();
if (!files.length) {
  console.error(`No .gltf files in ${IN}`);
  process.exit(1);
}

const manifest = { units: 'mm', axes: { beam: 'z', up: 'y' }, systems: [], parts: [] };
let totalIn = 0;
let totalOut = 0;
const t0 = Date.now();

for (const [fi, file] of files.entries()) {
  const system = basename(file, '.gltf');
  const src = await io.read(resolve(IN, file));
  const prims = [];
  for (const mesh of src.getRoot().listMeshes()) {
    for (const p of mesh.listPrimitives()) {
      if (p.getMode() === Primitive.Mode.TRIANGLES) prims.push(triangles(p));
    }
  }
  const parts = classify(system, prims);
  // Make roles unique within a system (disks_pz, disks_pz_2, ...).
  const seen = new Map();
  for (const p of parts) {
    const base = p.sign ? `${p.role}_${p.sign > 0 ? 'pz' : 'nz'}` : p.role;
    const k = (seen.get(base) ?? 0) + 1;
    seen.set(base, k);
    p.role = k === 1 ? base : `${base}_${k}`;
  }

  const doc = new Document();
  doc.getRoot().getAsset().generator = 'ddgeoviztools web/scripts/build-models.mjs';
  const buffer = doc.createBuffer();
  const scene = doc.createScene(system);
  const material = doc.createMaterial(groupOf(system)).setMetallicFactor(0.5).setRoughnessFactor(0.5);

  let sysTris = 0;
  for (const part of parts) {
    const id = `${system}/${part.role}`;
    const pos = doc.createAccessor().setType('VEC3').setArray(part.tris).setBuffer(buffer);
    // No NORMAL attribute on purpose: the page renders with flatShading, which
    // derives face normals in the fragment shader. Storing per-face normals
    // would triple the vertex count (18 MB instead of ~5 MB on the wire).
    const prim = doc.createPrimitive().setAttribute('POSITION', pos).setMaterial(material);
    const mesh = doc.createMesh(id).addPrimitive(prim);
    scene.addChild(doc.createNode(id).setMesh(mesh));

    const b = bounds(part.tris);
    const n = triCount(part.tris);
    sysTris += n;
    manifest.parts.push({
      id,
      system,
      group: groupOf(system),
      role: part.role,
      sign: part.sign,
      tris: n,
      bbox: { min: b.min.map(Math.round), max: b.max.map(Math.round) },
      rMin: Math.round(b.rMin),
      rMax: Math.round(b.rMax),
      rMid: Math.round((b.rMin + b.rMax) / 2),
      zMid: Math.round((b.min[2] + b.max[2]) / 2),
      center: centroid(part.tris).map(Math.round),
    });
  }

  await doc.transform(
    weld(),
    quantize({ quantizePosition: 14 }),
    meshopt({ encoder: MeshoptEncoder, level: 'medium' }),
    prune(),
  );
  const outPath = resolve(OUT, `${system}.glb`);
  await io.write(outPath, doc);

  const inBytes = statSync(resolve(IN, file)).size;
  const outBytes = statSync(outPath).size;
  totalIn += inBytes;
  totalOut += outBytes;
  manifest.systems.push({ system, file: `${system}.glb`, group: groupOf(system), bytes: outBytes, tris: sysTris, parts: parts.map((p) => p.role) });

  const pct = Math.round(((fi + 1) / files.length) * 100);
  const el = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(
    `[${String(pct).padStart(3)}%] ${system.padEnd(22)} ${String(parts.length).padStart(2)} parts ` +
      `${String(sysTris).padStart(8)} tris  ${(inBytes / 1e6).toFixed(2).padStart(6)} MB → ${(outBytes / 1e6).toFixed(2).padStart(5)} MB  (${el}s)`,
  );
}

writeFileSync(resolve(OUT, 'parts.json'), JSON.stringify(manifest, null, 1));
console.log(`\n${files.length} systems, ${manifest.parts.length} parts, ${(totalIn / 1e6).toFixed(1)} MB → ${(totalOut / 1e6).toFixed(2)} MB`);
console.log(`wrote ${OUT}/parts.json`);
