// Scene — renderer, environment, model loading and the explode/emphasis
// application. Geometry is in GDML mm; the root group is scaled to metres.
import {
  WebGLRenderer, Scene, PerspectiveCamera, Group, Vector3, Color,
  ACESFilmicToneMapping, SRGBColorSpace, PMREMGenerator, DirectionalLight,
  HemisphereLight, Mesh, MeshStandardMaterial, FrontSide, DoubleSide,
} from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { makeMaterials } from './palette.js';
import { ease } from './scroll.js';

const BASE = import.meta.env.BASE_URL;

export class DetectorScene {
  constructor(canvas) {
    this.canvas = canvas;
    // ?fast: cheap materials, no environment map, no MSAA. For software-GL
    // test runners (SwiftShader) where the physical shader takes seconds per
    // frame; never used by real visitors.
    this.fast = new URLSearchParams(location.search).has('fast');
    this.renderer = new WebGLRenderer({ canvas, antialias: !this.fast, alpha: true, powerPreference: 'high-performance' });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    this.maxDpr = Math.min(devicePixelRatio || 1, innerWidth < 720 ? 1.5 : 2);
    this.dpr = this.maxDpr;
    this.renderer.setPixelRatio(this.dpr);

    this.scene = new Scene();
    this.camera = new PerspectiveCamera(32, 1, 0.05, 200);
    this.root = new Group();
    this.root.scale.setScalar(0.001);
    this.scene.add(this.root);

    // Environment: procedural room through PMREM (no HDR file needed) plus a
    // warm key / cool fill echoing the Blender colour-temperature rig.
    if (!this.fast) {
      const pmrem = new PMREMGenerator(this.renderer);
      this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      pmrem.dispose();
    }
    const key = new DirectionalLight(new Color(1.0, 0.78, 0.55), 2.2);
    key.position.set(8, 12, 6);
    const fill = new DirectionalLight(new Color(0.72, 0.82, 1.0), 0.9);
    fill.position.set(-10, 3, -8);
    const rim = new DirectionalLight(new Color(0.9, 0.95, 1.0), 1.4);
    rim.position.set(-4, 6, 14);
    this.scene.add(key, fill, rim, new HemisphereLight(0x3a4250, 0x05060a, 0.5));

    this.materials = makeMaterials();
    this.parts = []; // { id, system, group, role, sign, mesh, dir, amp, row }
    this.frameTimes = [];
    this.resize();
  }

  resize() {
    const w = innerWidth;
    const h = innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  /** Load every system GLB listed in parts.json. onProgress(0..1). */
  async load(onProgress = () => {}) {
    const manifest = await (await fetch(`${BASE}models/parts.json`)).json();
    // ?lite skips the heaviest systems (>100k triangles) — used for quick
    // visual checks on software-GL test runners, never in production.
    if (new URLSearchParams(location.search).has('lite')) {
      manifest.systems = manifest.systems.filter((s) => s.tris < 100000);
    }
    this.manifest = manifest;
    // GLTFLoader sanitises node names (drops '/', '.', ':' …), so index the
    // manifest under both the raw id and its sanitised form.
    const sanitize = (n) => n.replace(/[\[\]\.:\/]/g, '');
    const rows = new Map(manifest.parts.flatMap((p) => [[p.id, p], [sanitize(p.id), p]]));
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    const total = manifest.systems.reduce((s, x) => s + x.bytes, 0);
    const got = new Map();
    const report = () => onProgress(Math.min(1, [...got.values()].reduce((a, b) => a + b, 0) / total));

    await Promise.all(
      manifest.systems.map(
        (sys) =>
          new Promise((res, rej) =>
            loader.load(
              `${BASE}models/${sys.file}`,
              (gltf) => {
                got.set(sys.system, sys.bytes);
                report();
                // Collect first: addPart() re-parents the mesh, which would
                // mutate the children array traverse() is walking.
                const found = [];
                gltf.scene.traverse((o) => {
                  if (o instanceof Mesh && rows.has(o.name)) found.push([o, rows.get(o.name)]);
                });
                for (const [o, row] of found) this.addPart(o, row);
                if (!found.length) console.warn(`no manifest parts matched in ${sys.file}`);
                res();
              },
              (ev) => { got.set(sys.system, Math.min(ev.loaded, sys.bytes)); report(); },
              rej,
            ),
          ),
      ),
    );
    this.parts.sort((a, b) => a.row.rMid - b.row.rMid);
    this.systems = manifest.systems;
  }

  addPart(mesh, row) {
    const base = this.materials[row.group] ?? this.materials.other;
    const mat = this.fast
      ? new MeshStandardMaterial({ color: base.color, metalness: 0.2, roughness: 0.7, flatShading: true, transparent: true })
      : base.clone();
    mat.userData.group = row.group;
    mesh.material = mat;
    mesh.frustumCulled = false; // parts move; cheap enough with ~90 draws
    // The GLB node carries a de-quantisation translation/scale from
    // KHR_mesh_quantization, so never touch mesh.position. Animate a pivot.
    const pivot = new Group();
    pivot.name = row.id;
    pivot.add(mesh);
    this.root.add(pivot);

    // Explode direction & amplitude (mm), from the geometry itself.
    const c = row.center;
    const dir = new Vector3();
    let amp = 0;
    if (row.sign !== 0) {
      dir.set(0, 0, row.sign);
      amp = 0.55 * Math.abs(row.zMid) + 400;
    } else if (/^stave/.test(row.role)) {
      dir.set(c[0], c[1], 0).normalize();
      amp = 0.32 * row.rMid + 250;
    } else if (/^layer/.test(row.role)) {
      // Concentric shells telescope along the beam axis, centred on the
      // middle layer so the set reads as a progression.
      dir.set(0, 0, 1);
      amp = 0; // set in indexLayers()
    } else {
      dir.set(0, 0, 0);
    }
    this.parts.push({ id: row.id, system: row.system, group: row.group, role: row.role, sign: row.sign, mesh, pivot, dir, amp, row });
    this.indexLayers(row.system);
  }

  /** Give layerN parts of a system a symmetric telescoping offset. */
  indexLayers(system) {
    const layers = this.parts.filter((p) => p.system === system && /^layer/.test(p.role)).sort((a, b) => a.row.rMid - b.row.rMid);
    const n = layers.length;
    if (!n) return;
    layers.forEach((p, i) => {
      const len = p.row.bbox.max[2] - p.row.bbox.min[2];
      const k = i - (n - 1) / 2; // …, -1, 0, +1, …
      p.amp = Math.abs(k) * (len * 1.15);
      p.dir.set(0, 0, Math.sign(k) || 0);
    });
  }

  /** Which explode rule governs a part, if any. */
  ruleFor(p) {
    if (/^stave/.test(p.role)) return `staves.${p.group}`;
    if (p.sign !== 0 && /Endcap$/.test(p.system)) return `endcaps.${p.group}`;
    if (/^layer/.test(p.role)) return `layers.${p.system}`;
    if (/^disks/.test(p.role)) return `disks.${p.system}`;
    if (/^Nozzle/.test(p.system)) return 'nozzles';
    return null;
  }

  /**
   * Apply an interpolated state: { explode: {rule: amount}, opacity: {group: a} }.
   * `stagger` in [0,1] shifts staves so the peel ripples around the barrel.
   */
  apply(state) {
    for (const p of this.parts) {
      const rule = this.ruleFor(p);
      let a = rule ? state.explode[rule] ?? 0 : 0;
      if (/^stave/.test(p.role)) {
        // Ripple: stave i reaches full extension slightly after stave i-1.
        const i = parseInt(p.role.slice(5), 10);
        const delay = ((i * 7) % 12) / 12 * 0.35;
        a = ease.clamp01((a - delay) / (1 - 0.35));
        a = ease.inOut(a);
      } else {
        a = ease.inOut(a);
      }
      p.pivot.position.copy(p.dir).multiplyScalar(a * p.amp);

      // Service tubes and supports stay quiet even when their system is the subject.
      const quiet = /^(shell|support)/.test(p.role) ? 0.35 : 1;
      const op = (state.opacity[p.group] ?? 1) * quiet;
      const m = p.mesh.material;
      m.opacity = op;
      m.depthWrite = op > 0.5;
      m.transparent = op < 0.999;
      // Ghosts render front faces only, so a sight line through several
      // nested shells does not accumulate into a muddy veil.
      m.side = op < 0.5 ? FrontSide : DoubleSide;
    }
  }

  render(dt) {
    const t0 = performance.now();
    this.renderer.render(this.scene, this.camera);
    // Adaptive resolution: if we keep missing ~45 fps, drop DPR by 0.25 (min 1).
    this.frameTimes.push(performance.now() - t0 + dt * 0);
    if (this.frameTimes.length >= 40) {
      const avg = this.frameTimes.reduce((a, b) => a + b, 0) / this.frameTimes.length;
      this.frameTimes.length = 0;
      if (avg > 22 && this.dpr > 1) { this.dpr = Math.max(1, this.dpr - 0.25); this.renderer.setPixelRatio(this.dpr); }
      else if (avg < 9 && this.dpr < this.maxDpr) { this.dpr = Math.min(this.maxDpr, this.dpr + 0.25); this.renderer.setPixelRatio(this.dpr); }
    }
  }
}
