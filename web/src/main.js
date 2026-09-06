// main.js — bootstrap: build the story DOM from chapters, load the models,
// then run one animation loop that turns smoothed scroll progress into
// camera, explode, emphasis, copy and callouts.
import { Vector3, Box3 } from 'three';
import { chapters, RULES, SYSTEMS, SYSTEM_GROUP } from './chapters.js';
import { ScrollEngine, ease } from './scroll.js';
import { DetectorScene } from './scene.js';
import { Labels } from './labels.js';

const params = new URLSearchParams(location.search);
// ?still disables the hero idle rotation (deterministic screenshots); reduced
// motion does the same and also makes the scroll spring snap.
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const still = params.has('still') || reduced;
window.__maia = { frameMs: 0, frames: 0 };

// ---------- story DOM ----------
const story = document.getElementById('story');
const sections = chapters.map((c) => {
  const sec = document.createElement('section');
  sec.className = `chapter${c.cls ? ` ${c.cls}` : ''}`;
  sec.dataset.side = c.side;
  sec.id = c.id;
  const facts = c.facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  sec.innerHTML = c.colophon
    ? `<div class="copy colophon">
         <p>Geometry: MAIA_260530, DD4hep compact → GDML → GLTF with
         <a href="https://github.com/lawrenceleejr/ddgeoviztools">ddgeoviztools</a>.<br/>
         Rendered live in WebGL from 90 meshopt-compressed parts (4.7 MB). Materials follow the Blender pipeline palette.</p>
       </div>`
    : `<div class="copy">
         ${c.eyebrow ? `<p class="eyebrow">${c.eyebrow}</p>` : ''}
         ${c.headline ? `<h${c.cls === 'hero' ? 1 : 2} class="headline">${c.headline}</h${c.cls === 'hero' ? 1 : 2}>` : ''}
         ${c.lede ? `<p class="lede">${c.lede}</p>` : ''}
         ${facts ? `<dl class="facts">${facts}</dl>` : ''}
         ${c.hint ? `<div class="scroll-hint">${c.hint}</div>` : ''}
       </div>`;
  story.appendChild(sec);
  return sec;
});

// ---------- WebGL or fallback ----------
const canvas = document.getElementById('gl');
const loader = document.getElementById('loader');
const fill = loader.querySelector('.loader-fill');
const note = loader.querySelector('.loader-note');

function hasWebGL() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch { return false; }
}

const engine = new ScrollEngine(sections, { reduced: still });
window.__maia.engine = engine;

if (!hasWebGL()) {
  loader.classList.add('done');
  const n = document.createElement('p');
  n.className = 'fallback-note';
  n.textContent = 'WebGL is unavailable in this browser, so the 3D view is hidden.';
  document.body.appendChild(n);
  (function loop() {
    const t = engine.step(1 / 60);
    setActive(t);
    requestAnimationFrame(loop);
  })();
} else {
  boot().catch((err) => {
    console.error(err);
    note.textContent = 'Could not load the geometry.';
  });
}

function setActive(t) {
  const i = Math.floor(t);
  const f = t - i;
  sections.forEach((s, k) => s.classList.toggle('active', k === i ? f < 0.62 : k === i + 1 ? f >= 0.62 : false));
}

// ---------- state interpolation ----------
function denseState(c) {
  const explode = Object.fromEntries(RULES.map((r) => [r, c.state.explode[r] ?? 0]));
  const opacity = Object.fromEntries(SYSTEMS.map((sys) => [sys, c.state.focus.includes(sys) || c.state.focus.includes(SYSTEM_GROUP[sys]) ? 1 : c.state.ghost]));
  return { explode, opacity };
}
const states = chapters.map(denseState);

function blendState(a, b, w) {
  const explode = {};
  for (const r of RULES) explode[r] = ease.lerp(a.explode[r], b.explode[r], w);
  const opacity = {};
  for (const sys of SYSTEMS) opacity[sys] = ease.lerp(a.opacity[sys], b.opacity[sys], w);
  return { explode, opacity };
}

/** Within a chapter: hold, then transition to the next over the middle band. */
function transitionWeight(f) {
  return ease.inOut((f - 0.3) / 0.55);
}

async function boot() {
  const scene = new DetectorScene(canvas);
  window.__maia.scene = scene; // debug / test hook
  await scene.load((p) => { fill.style.width = `${Math.round(p * 100)}%`; });
  const labels = new Labels(document.getElementById('labels'), document.getElementById('leaders'), scene.camera, scene.root, new Map(scene.parts.map((p) => [p.id, p])));
  note.textContent = '';
  loader.classList.add('done');
  addEventListener('resize', () => scene.resize());

  const pos = new Vector3();
  const tgt = new Vector3();
  const a = new Vector3();
  const b = new Vector3();
  let last = performance.now();
  let idle = 0;
  let warm = 3; // always draw the first few frames
  let lastT = -1;
  // ?cam=x,y,z[,tx,ty,tz] pins the camera (debug / framing checks).
  const camOverride = params.get('cam')?.split(',').map(Number);
  {
    const box = new Box3().setFromObject(scene.root);
    console.log('[maia] root bbox (m)', box.min.toArray().map((v) => v.toFixed(2)), box.max.toArray().map((v) => v.toFixed(2)));
  }

  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    // The spring may briefly undershoot 0 or overshoot the end; clamp.
    const t = Math.min(chapters.length - 1e-6, Math.max(0, engine.step(dt)));
    const i = Math.min(chapters.length - 1, Math.floor(t));
    const f = t - i;
    const j = Math.min(chapters.length - 1, i + 1);
    const w = i === j ? 0 : transitionWeight(f);

    // Camera: spherical-ish interpolation by lerping position and target.
    const ca = chapters[i].camera;
    const cb = chapters[j].camera;
    pos.lerpVectors(a.set(...ca.pos), b.set(...cb.pos), w);
    tgt.lerpVectors(a.set(...ca.target), b.set(...cb.target), w);
    scene.camera.fov = ease.lerp(ca.fov, cb.fov, w);
    // Phones: back the camera off so the model fits the narrow frame.
    if (innerWidth <= 720) pos.sub(tgt).multiplyScalar(1.4).add(tgt);
    scene.camera.position.copy(pos);
    scene.camera.lookAt(tgt);
    // Screen-space shift: slide the camera along its own right axis so the
    // model sits opposite the copy. On narrow screens the copy is below, so
    // no shift.
    const narrow = innerWidth <= 720;
    const shift = narrow ? 0 : ease.lerp(ca.shift ?? 0, cb.shift ?? 0, w);
    const dist = pos.distanceTo(tgt);
    const visH = 2 * dist * Math.tan((scene.camera.fov * Math.PI) / 360);
    if (shift) scene.camera.translateX(-shift * visH * scene.camera.aspect);
    // Phones: copy sits at the bottom, so lift the model into the top half.
    if (narrow) scene.camera.translateY(-0.32 * visH);
    if (camOverride) {
      scene.camera.position.set(camOverride[0], camOverride[1], camOverride[2]);
      scene.camera.lookAt(camOverride[3] ?? 0, camOverride[4] ?? 0, camOverride[5] ?? 0);
      scene.camera.fov = 40;
    }
    scene.camera.updateProjectionMatrix();

    // Hero idle rotation, blended out as we leave the first chapter.
    const heroW = 1 - ease.inOut(t / 0.8);
    const spinning = !still && heroW > 0.001;
    if (spinning) idle += dt * 0.06;
    scene.root.rotation.y = idle * heroW;
    scene.root.updateMatrixWorld();

    // Render on demand: skip the GPU when nothing moved (scroll at rest, no
    // idle spin). Copy and label DOM updates are cheap and always run.
    const moving = t !== lastT || engine.velocity !== 0 || engine.value !== engine.target;
    lastT = t;
    const draw = moving || spinning || warm > 0;
    if (warm > 0) warm--;

    scene.apply(blendState(states[i], states[j], w));
    setActive(t);

    // Callouts belong to the chapter whose copy is active.
    const li = f < 0.62 ? i : j;
    labels.set(chapters[li].labels, li, chapters[li].side === 'right' ? -1 : 1);
    labels.update(Math.abs(t - li) < 0.45 || (li === i && f < 0.55));

    if (draw) {
      const t0 = performance.now();
      scene.render(dt);
      window.__maia.frameMs = performance.now() - t0;
      window.__maia.frames++;
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
