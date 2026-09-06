// main.js — bootstrap: build the story DOM from chapters, load the models,
// then run one animation loop that turns smoothed scroll progress into
// camera, explode, emphasis, copy and callouts.
import { Vector3 } from 'three';
import { chapters, RULES, GROUPS } from './chapters.js';
import { ScrollEngine, ease } from './scroll.js';
import { DetectorScene } from './scene.js';
import { Labels } from './labels.js';

const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

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

const engine = new ScrollEngine(sections, { reduced });

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
  const opacity = Object.fromEntries(GROUPS.map((g) => [g, c.state.focus.includes(g) ? 1 : c.state.ghost]));
  return { explode, opacity };
}
const states = chapters.map(denseState);

function blendState(a, b, w) {
  const explode = {};
  for (const r of RULES) explode[r] = ease.lerp(a.explode[r], b.explode[r], w);
  const opacity = {};
  for (const g of GROUPS) opacity[g] = ease.lerp(a.opacity[g], b.opacity[g], w);
  return { explode, opacity };
}

/** Within a chapter: hold, then transition to the next over the middle band. */
function transitionWeight(f) {
  return ease.inOut((f - 0.3) / 0.55);
}

async function boot() {
  const scene = new DetectorScene(canvas);
  const labels = new Labels(document.getElementById('labels'), document.getElementById('leaders'), scene.camera, scene.root);
  await scene.load((p) => { fill.style.width = `${Math.round(p * 100)}%`; });
  note.textContent = '';
  loader.classList.add('done');
  addEventListener('resize', () => scene.resize());

  const pos = new Vector3();
  const tgt = new Vector3();
  const a = new Vector3();
  const b = new Vector3();
  let last = performance.now();
  let idle = 0;

  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const t = engine.step(dt);
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
    scene.camera.position.copy(pos);
    scene.camera.lookAt(tgt);
    scene.camera.updateProjectionMatrix();

    // Hero idle rotation, blended out as we leave the first chapter.
    if (!reduced) idle += dt * 0.06;
    const heroW = 1 - ease.inOut(t / 0.8);
    scene.root.rotation.y = idle * heroW;
    scene.root.updateMatrixWorld();

    scene.apply(blendState(states[i], states[j], w));
    setActive(t);

    // Callouts belong to the chapter whose copy is active.
    const li = f < 0.62 ? i : j;
    labels.set(chapters[li].labels, li);
    labels.update(Math.abs(t - li) < 0.45 || (li === i && f < 0.55));

    scene.render(dt);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
