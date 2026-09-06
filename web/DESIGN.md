# MAIA exploded view — look and tool stack

A single scrolling page that takes the MAIA muon-collider detector apart,
one system at a time, from the beam pipe outward. It is built like an
Apple hardware page: one object on a near-black stage, a camera that
moves only when you scroll, and very little text, all of it true.

Live at `https://lawrenceleejr.github.io/ddgeoviztools/` once Pages is
enabled (see *Deploy*).

## The look

**Stage.** A void, not a room. Background `#07080a` with a barely-there
radial lift behind the detector (`#101318` at centre). No floor, no
grid, no axes. Depth comes from a soft rim light, physically based
materials, and the way parts dim when they are not the subject.

**Materials.** The palette is the one already used by the Blender
pipeline (`src/gdml_to_blender.py`), so stills, the UE5 app, and the web
page agree:

| System | Base colour (linear) | Metal | Rough | Finish note |
|---|---|---|---|---|
| Beam pipe | 0.78 0.79 0.82 | 0.80 | 0.40 | stainless, slight anisotropy |
| Vertex | 0.28 0.45 0.72 | 0.70 | 0.45 | steel blue |
| Inner / outer tracker | 0.22 0.38 0.60 | 0.55 | 0.50 | silicon blue, clearcoat 0.3 |
| Solenoid | 0.72 0.42 0.22 | 0.80 | 0.45 | brushed copper |
| ECal | 0.35 0.62 0.52 | 0.10 | 0.35 | pale aqua, clearcoat 0.6 |
| HCal | 0.52 0.38 0.22 | 0.70 | 0.55 | iron / brass |
| Yoke | 0.30 0.28 0.26 | 0.75 | 0.60 | dark iron |
| Nozzle (W) | 0.42 0.40 0.38 | 0.85 | 0.40 | tungsten |
| Nozzle cladding (BCH) | 0.92 0.91 0.90 | 0.00 | 0.95 | white diffuse |

Lighting is a procedurally generated environment (three.js
`RoomEnvironment` through PMREM) plus one warm key light at 3200 K and a
cool fill at 6500 K, echoing the colour-temperature rig in the Blender
scene. ACES filmic tone mapping at exposure 1.1.

**Emphasis.** The current subject renders at full material. Everything
else drops to 25 % opacity and slightly desaturates. That is the whole
highlighting system: no outlines, no glow.

**Motion.** The camera and the explosion are pure functions of scroll
position, smoothed by a critically damped spring so trackpad inertia
reads as camera weight. Nothing plays on a timer except a slow idle
rotation in the hero. Users with `prefers-reduced-motion` get the same
scenes as cross-fades with the camera still.

**Typography.** Two families, one job each, plus a mono for numbers.
All self-hosted from Google Fonts (`public/fonts`).

| Role | Face | Weight | Size (1.25 scale from 17 px) |
|---|---|---|---|
| Display | Inter Tight | 200 / 300 | 66 → 41 px, tracking −0.02 em, line-height 1.05 |
| Body | Inter | 400 / 500 | 17 px, line-height 1.5, measure ≤ 52 ch |
| Callout numerals | IBM Plex Mono | 400 | 13.6 px, tabular |
| Eyebrow | Inter | 500 | 13.6 px, uppercase, tracking 0.12 em |

Text is `#f2f3f5` on the dark stage; secondary text `#9a9fa8`; hairlines
`rgba(255,255,255,0.18)`.

**Tufte.** Every callout is a direct label anchored to the part it
measures: a 1 px hairline from a point on the geometry to a short mono
label such as `r = 1 486 mm`. No legends, no boxes, no icons. The only
decoration is the detector.

## Chapters

Scroll is divided into eleven chapters. Each is one viewport tall of
copy, with the canvas pinned behind. Progress within a chapter drives
the camera keyframe pair and the explode amount for the parts named.

| # | Chapter | Camera | Motion | Callouts (all from the GDML) |
|---|---|---|---|---|
| 0 | MAIA | 3/4 view, far | slow idle yaw, fully assembled | 11.8 m across, 11.9 m long |
| 1 | Beam pipe & vertex | dolly to 0.4 m from IP | outer systems fade to 8 %, vertex barrel layers fan +r | Be pipe Ø 48 mm · 5 layers r 30–102 mm · 4 disk pairs |
| 2 | Inner tracker | pull back, low angle | 3 barrel layers fan +r, disks slide ±z | r 127 / 340 / 554 mm · 7 disk pairs to |z| 2.19 m |
| 3 | Outer tracker | side-on | layers fan +r one after another | r 819 / 1 153 / 1 486 mm · silicon |
| 4 | Solenoid | orbit 90° | coil slides +y out of the calorimeters | 5 T · Ø 3.7 m · 4.6 m long |
| 5 | ECal | high 3/4 | 12 staves peel radially, endcaps slide ±z | 50 layers × 2.2 mm W · r 1.86–2.12 m |
| 6 | HCal | wide | staves peel, endcaps slide | 75 layers × 19 mm steel · r 2.13–4.11 m |
| 7 | Yoke | wider | staves peel, endcaps slide | 4 layers × 436 mm steel · r 4.15–5.90 m |
| 8 | Nozzles | along the beam | tungsten cones slide ±z out of the endcaps | W + BCH2 · |z| 0.06–5.95 m |
| 9 | Exploded | far, slight top-down | everything at full explode, all labels on | one label per system |
| 10 | Colophon | hold | slow reassembly to the hero pose | geometry `MAIA_260530` · ddgeoviztools |

Explode geometry is data-driven from `public/models/parts.json`: barrel
parts move along their radial midpoint direction, endcap and forward
parts move along ±z, staves move radially by stave index with a small
stagger. Amplitudes are a fraction of the part's own radius so the
picture keeps its proportions.

## Tool stack

| Layer | Choice | Why |
|---|---|---|
| Renderer | three.js r185, WebGL2 | Real geometry, per-layer explode, crisp at any DPR. Cycles frames would need hours of CPU render per revision in CI and give no interactivity. |
| Bundler / dev | Vite 8 | Zero-config ES modules, `base` for the Pages subpath, fast preview. |
| Assets | `@gltf-transform` + `meshoptimizer` (`scripts/build-models.mjs`) | Strip VTK point/line primitives, split into 90 named parts, 14-bit quantisation, meshopt compression. 46.8 MB → 4.7 MB. No normals are stored: the page uses flat shading, which derives them in the fragment shader. |
| Scroll | Hand-rolled: `scrollY` → chapter progress → damped spring | ~60 lines, no dependency, deterministic, works with native inertia. GSAP ScrollTrigger and Lenis were considered and rejected for licence and weight. |
| Fonts | Google Fonts, self-hosted woff2 | No runtime CDN request. |
| Labels | DOM elements projected from 3D each frame | Selectable text, real fonts, hairlines as SVG. |
| Deploy | GitHub Actions → Pages (`.github/workflows/pages.yml`) | Rebuilds the models and the site on every push, so the published page can never drift from the committed geometry. Nothing built is committed. |
| Verification | Playwright (`scripts/screenshots.mjs`) | Scrolls chapter by chapter and screenshots each for visual review. |

## Assets

`npm run models` reads `../data/output/*.gltf` and writes
`public/models/<System>.glb` plus `public/models/parts.json`. Each GLB
holds one node per part:

- barrels: one part per stave (`ECalBarrel/stave07`), classified by the
  azimuth of the primitive centroid;
- endcaps: `pz` and `nz` halves (the VTK export already emits them as
  two primitives; tracker disks that span both sides are split by
  triangle);
- trackers and vertex: `layerN` by radius (radial clustering of module
  centroids), `disks_pz` / `disks_nz` (two-sided primitives split by
  triangle), `shell` for thin service tubes, `support` for the rest.

`parts.json` rows: `{ id, system, group, role, sign, tris, bbox, rMin, rMax, rMid, zMid, center }`.

## Testing without a GPU

Software GL (SwiftShader in headless Chromium) takes seconds per frame on
the physical shader, so the page has test-only query flags:

| Flag | Effect |
|---|---|
| `?still` | no idle rotation; the scroll spring snaps (also implied by reduced motion) |
| `?fast` | cheap material, no environment map, no MSAA |
| `?lite` | skip systems over 100 k triangles |
| `?cam=x,y,z[,tx,ty,tz]` | pin the camera (metres) |

`npm run shots` drives the built site through every chapter and writes
`shots/NN-<chapter>.png`; `--full 1` keeps the full geometry.

## Budgets

- Models on the wire ≤ 6 MB, first-paint JS ≤ 250 kB gzip.
- 60 fps on an integrated-GPU laptop at DPR ≤ 1.5; DPR clamped to 1 on
  phones and when the frame budget is missed.
- No WebGL → a static poster of the exploded view and the same copy.

## Deploy

`.github/workflows/pages.yml` runs on every push that touches `web/`: it
installs, regenerates the packed GLBs from `data/output/`, builds the
site and publishes `web/dist` to GitHub Pages. No build output is
committed, so the source is the single record of what ships.

Repository setting (once): **Settings → Pages → Source → GitHub
Actions**. The `configure-pages` step also sets this itself on its first
successful run. The site is then at
`https://lawrenceleejr.github.io/ddgeoviztools/`.

The workflow is set to run from `main` and from the branch this work sits
on. GitHub restricts the `github-pages` environment to the repository's
default branch, so publishing from any other branch also needs that
branch added under **Settings → Environments → github-pages → Deployment
branches**; without it the deploy job stops on a protection rule.
