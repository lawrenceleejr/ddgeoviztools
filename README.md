# ddgeoviztools

CLI tools for working with ddsim/DD4hep GDML detector geometries:

1. **Split** — divide a monolithic GDML into one file per sub-detector system.
2. **Convert** — convert a GDML file to OBJ, GLTF, or VTP for visualization.
3. **Split-convert** — do both in one command.
4. **Blender-scene** — build a ready-to-use `.blend` file from the converted
   meshes, with physics-inspired materials, a phi-cutaway, and standard HEP
   camera views.
5. **Web viewer** — an interactive, third-person 3D walkthrough of the detector
   in the browser, with Cycles lighting baked in. See
   [Web viewer](#web-viewer-interactive-3d-walkthrough).

Everything runs inside a Docker container — no local Python environment or
library installation required.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (any recent version)
- Your GDML file, e.g. `MAIA_260226.gdml`, in the directory where you run
  the commands.

---

## Quick start

```bash
# Clone the repo and enter it
git clone <repo-url>
cd ddgeoviztools

# Make the wrapper executable (one time)
chmod +x run.sh

# First run builds the Docker image automatically (~5-10 min)
./run.sh --help
```

---

## Workflow with `MAIA_260226.gdml`

Place `MAIA_260226.gdml` in your working directory (or any directory you
prefer — just `cd` there first). All paths inside the container start with
`/data`, which maps to your current directory on the host.

### 0. (Optional) Generate the GDML from a DD4hep compact XML

If you only have the DD4hep compact description and not the flattened
GDML, `scripts/compact_to_gdml.sh` runs DD4hep's `geoConverter` inside a
Docker container — no local DD4hep / ROOT / Geant4 install needed. The
default image is the legacy Muon Collider simulation stack
(`ghcr.io/muoncollidersoft/mucoll-sim-alma9:legacy-2.x`), which ships
DD4hep + the MuC detector model pre-configured and provides the legacy
`_o1_v0X` detector plugin variants MAIA's compact still references.
The newer `mucoll-sim-ubuntu24:v2.11-amd64` image is faster but has
ABI mismatches against MAIA's older plugin set.

```bash
# Default output: alongside the compact, .xml → .gdml
./scripts/compact_to_gdml.sh /path/to/MAIA/compact/MAIA.xml

# Custom output path
./scripts/compact_to_gdml.sh MAIA.xml -o /tmp/MAIA_260226.gdml

# Use a different DD4hep image (e.g. plain AIDASoft DD4hep)
./scripts/compact_to_gdml.sh MAIA.xml \
    --image ghcr.io/aidasoft/dd4hep:latest

# Pull the image first (e.g. to refresh to the latest tag)
./scripts/compact_to_gdml.sh MAIA.xml --pull

# Debug XInclude / plugin errors interactively
./scripts/compact_to_gdml.sh MAIA.xml --shell
```

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--out PATH` | `<compact>.gdml` | Output GDML path |
| `--image NAME` | `ghcr.io/muoncollidersoft/mucoll-sim-alma9:legacy-2.x` | Docker image with DD4hep |
| `--pull` | off | `docker pull` the image before running |
| `--shell` | off | Drop into bash inside the container with the mounts in place |

These HEP images need a per-image init script sourced before `geoConverter`
is on `PATH`. The script searches common paths in this order:

1. `$DDGDML_INIT` (host env var — overrides everything)
2. `/opt/ilcsoft/muonc/init_ilcsoft.sh` (Muon Collider stack)
3. `/opt/setup.sh`, `/setup.sh`
4. `/opt/spack-environments/*/activate.sh`, `/opt/*/setup.sh`

If your image puts its init somewhere else, set `DDGDML_INIT=/path/in/container`
on the host and re-run.

The script bind-mounts the compact file's parent directory as `/compact`
(read-only) so the XInclude'd materials / segmentations / sub-detector
XMLs resolve, and writes the GDML to a `/out` mount.

If your compact includes files from **outside** that parent directory,
either copy them in first or use `--shell` to set up custom mounts by
hand. `geoConverter` inside the container is invoked as:

```
geoConverter -compact2gdml -input /compact/<input.xml> -output /out/<output.gdml>
```

### 1. Split into sub-detector GDMLs

```bash
./run.sh split \
    /data/MAIA_260226.gdml \
    --output-dir /data/split_gdml/
```

Output: one `.gdml` file per sub-detector in `./split_gdml/`.

```
split_gdml/
├── EcalBarrel.gdml
├── EcalEndcap.gdml
├── HcalBarrel.gdml
├── Tracker.gdml
└── ...
```

### 2. Convert the full geometry to GLTF

```bash
./run.sh convert \
    /data/MAIA_260226.gdml \
    --output /data/MAIA_260226.gltf
```

Open `MAIA_260226.gltf` in [gltf.report](https://gltf.report), Blender, or
any GLTF viewer.

### 3. Convert to OBJ instead

```bash
./run.sh convert \
    /data/MAIA_260226.gdml \
    --output /data/MAIA_260226.obj
```

Produces `MAIA_260226.obj` and `MAIA_260226.mtl`.

### 4. Split and convert every sub-detector in one step

```bash
./run.sh split-convert \
    /data/MAIA_260226.gdml \
    --output-dir /data/output/ \
    --format gltf
```

Output layout:

```
output/
├── gdml/
│   ├── EcalBarrel.gdml
│   ├── HcalBarrel.gdml
│   └── ...
├── EcalBarrel.gltf
├── HcalBarrel.gltf
└── ...
```

---

## All options

### `split`

```
./run.sh split GDML_FILE --output-dir DIR [--depth N] [--detectors D1,D2,...]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir` | *(required)* | Directory for split GDML files |
| `--depth N` | `1` | Levels below world volume to split at. Use `1` for direct daughters (standard ddsim layout). Use `2` if the world has one top-level envelope that contains the actual sub-detectors. |
| `--detectors D1,D2` | all | Only output named sub-detectors (comma-separated logical-volume names) |

**Example — split two detectors only:**

```bash
./run.sh split \
    /data/MAIA_260226.gdml \
    --output-dir /data/split_gdml/ \
    --detectors EcalBarrel_lv,HcalBarrel_lv
```

**Example — split at depth 2:**

```bash
./run.sh split \
    /data/MAIA_260226.gdml \
    --output-dir /data/split_gdml/ \
    --depth 2
```

---

### `convert`

```
./run.sh convert GDML_FILE --output FILE [--format obj|gltf|vtp]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output` | *(required)* | Output file path (`.obj`, `.gltf`, `.glb`, `.vtp`) |
| `--format` | *(from extension)* | Force output format regardless of extension |

**Supported formats:**

| Format | Extension | Notes |
|--------|-----------|-------|
| GLTF | `.gltf` | JSON + embedded binary; open in Blender, gltf.report, Three.js |
| GLB  | `.glb`  | Binary GLTF (single file) |
| OBJ  | `.obj`  | Produces a `.mtl` material file alongside |
| VTP  | `.vtp`  | VTK PolyData XML; open in ParaView |

---

### `split-convert`

```
./run.sh split-convert GDML_FILE --output-dir DIR \
    [--format obj|gltf|vtp] [--depth N] [--detectors D1,D2,...] [--fail-fast]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir` | *(required)* | Root output directory |
| `--format` | `gltf` | Mesh format for all sub-detectors |
| `--depth` | `1` | Split depth (see `split`) |
| `--detectors` | all | Comma-separated LV name filter |
| `--fail-fast` | off | Abort on first conversion error (default: warn and continue) |

---

### `blender-scene`

```
./run.sh blender-scene MESH_DIR --output FILE \
    [--format gltf|obj|vtp] \
    [--phi-cut DEGREES] [--phi-min DEGREES] [--no-phi-cut] \
    [--weld-threshold MM]
```

Reads all `*.{format}` files from `MESH_DIR` (the output of `split-convert`)
and produces a `.blend` file with:

- One Blender object per sub-detector, each with a metal/matte material.
- A **Weld modifier** on every object to merge duplicate vertices from VTK
  tessellation (the primary mesh cleanup step).
- A **phi-cutaway** Geometry Nodes modifier that deletes faces outside the
  `[phi_min, phi_max]` sector. `phi = atan2(Y, X)` with Z = beam.
- A **`PhiCutawayControl`** Empty object whose custom properties (`phi_min`,
  `phi_max`) drive all sub-detectors simultaneously via Blender drivers.
- Three pre-built cameras (see coordinate system below).

| Flag | Default | Description |
|------|---------|-------------|
| `--format` | `gltf` | Input mesh format to look for in `MESH_DIR` |
| `--phi-cut` | `180` | Angular width of the visible sector in degrees. `180` = upper half `[0°,180°]`. `360` = full detector. |
| `--phi-min` | `0` | Starting angle of the visible sector (degrees). |
| `--no-phi-cut` | off | Disable the cutaway entirely (load full geometry). |
| `--weld-threshold` | `1e-4` | Distance (mm) for the Weld modifier. `0` to disable. |

**Example — full workflow for MAIA_260226.gdml:**

```bash
# Step 1: split and convert to GLTF
./run.sh split-convert \
    /data/MAIA_260226.gdml \
    --output-dir /data/output/ \
    --format gltf

# Step 2: build Blender scene (upper-half phi cut, default)
./run.sh blender-scene \
    /data/output/ \
    --output /data/MAIA_260226.blend

# Open MAIA_260226.blend in Blender
```

**More examples:**

```bash
# Full detector (no cutaway)
./run.sh blender-scene /data/output/ \
    --output /data/MAIA_full.blend --no-phi-cut

# Quarter-detector cutaway (right quadrant: phi in [-90°, 90°])
./run.sh blender-scene /data/output/ \
    --output /data/MAIA_quarter.blend \
    --phi-cut 180 --phi-min -90

# Tighter weld threshold for very fine geometry
./run.sh blender-scene /data/output/ \
    --output /data/MAIA_260226.blend \
    --weld-threshold 0.001
```

---

## Coordinate system

All three tools preserve the **collider physics convention** throughout:

| Axis | Direction |
|------|-----------|
| **Z** | beam axis (horizontal) |
| **Y** | up (towards sky) |
| **X** | horizontal (right-hand rule: X = Y × Z is satisfied) |

The GDML/Geant4 geometry is already in this frame; no rotation is applied.

In the Blender scene, three cameras are provided:

| Camera | Position | What you see |
|--------|----------|--------------|
| `Cam_Transverse` *(default)* | on +Z axis | XY cross-section — X right, Y up, Z(beam) into screen |
| `Cam_Side` | on +X axis | ZY plane — Z(beam) horizontal-right, Y up |
| `Cam_Perspective` | 3/4 angle | overview of the detector |

Switch cameras via **Scene Properties → Camera** dropdown, or press
`Numpad 0` to look through the active camera.

---

## Using the phi cutaway in Blender

After opening the `.blend` file, the phi cutaway **removes** (cuts away)
the sector defined by `[Phi Min, Phi Max]`, revealing the detector interior.
Default `[0°, 90°]` removes the upper-right quadrant.

### Global control: PhiCutawayControl empty

A single **PhiCutawayControl** empty object in the Cutters collection
controls all sub-detector cutaways simultaneously:

- Select **PhiCutawayControl** → **Properties → Object → Custom Properties**.
- Adjust `phi_min` and `phi_max` (degrees).  All sub-detectors update
  together (via drivers on Blender 4.x; via shared node group defaults
  on Blender 5.0+).

### 1. Geometry Nodes cutaway (primary — enabled by default)

The **PhiCutaway** GN modifier reads a pre-baked `phi_deg` face attribute
and **deletes** faces whose phi falls inside `[Phi Min, Phi Max]`.

- You can also adjust **Phi Min** / **Phi Max** per-object in the modifier
  inputs, or edit the shared node group defaults to change all objects.

### 2. Boolean DIFFERENCE cutaway (secondary — disabled by default)

The **PhiBoolean** modifier uses a solid wedge mesh (**PhiWedge** in the
Cutters collection) covering the cut sector.  Boolean DIFFERENCE subtracts
this sector from the detector.

- To enable: select a detector object → **Properties → Modifiers →
  PhiBoolean** → toggle the camera and monitor icons (show in render /
  show in viewport).
- **Note:** Boolean operations require manifold (watertight) meshes.
  VTK-exported meshes are often non-manifold, which can cause the Boolean
  to fail silently.  The GN cutaway above is more reliable.

### Phi convention

`phi = atan2(-X_local, Y_local)` in mesh local (GDML) coordinates.
After the Ry(+90°) rotation into Blender world space:
- `phi = 0°` → +Y (vertically up)
- `phi = 90°` → +Z (horizontal transverse)
- `phi = -90°` → −Z (horizontal transverse, opposite side)

To animate the cutaway opening (e.g. for a video), keyframe `phi_max`
on the PhiCutawayControl empty over a frame range.

You can also change the **Weld modifier threshold** per-object in
**Properties → Modifiers → Weld** to control how aggressively duplicate
vertices are merged.

---

## Rebuilding the Docker image

The image is built automatically on first use. To force a rebuild after
changing `Dockerfile` or `requirements.txt`:

```bash
docker rmi ddgeoviztools
./run.sh --help   # triggers rebuild
```

Or build explicitly:

```bash
docker build -t ddgeoviztools .
```

---

## How it works

### Splitting (no pyg4ometry required)

The splitter uses `lxml` to manipulate the GDML XML directly:

1. Parse the GDML and build lookup maps for `<define>`, `<materials>`,
   `<solids>`, and `<structure>` elements.
2. Walk from the world volume down `--depth` levels to identify sub-detector
   logical volumes.
3. For each sub-detector, recursively collect every dependent element:
   solids referenced by boolean operations, daughter logical volumes, materials,
   and define entries used for positions and rotations.
4. Write a self-contained GDML with only the needed elements, in topological
   order (dependencies before dependents).

Handles DD4hep-style `<assembly>` volumes, boolean solids
(`<subtraction>`, `<union>`, `<intersection>`, `<multiUnion>`), reflected
and scaled solids, and composite materials.

### Conversion (pyg4ometry + VTK)

The converter uses [pyg4ometry](https://pyg4ometry.readthedocs.io/) to read the
GDML and build a VTK scene, then exports using VTK's built-in exporters:

- `vtkGLTFExporter` for GLTF/GLB
- `vtkOBJExporter` for OBJ
- `vtkSingleVTPExporter` for VTP

VTK runs in fully offscreen mode via `xvfb-run` (a virtual framebuffer
inside the container) — no GPU or display needed.

### Blender scene creation (bpy + trimesh)

The `blender-scene` command uses [bpy](https://pypi.org/project/bpy/) (the
Blender 4.0 Python module) and [trimesh](https://trimesh.org/):

1. **trimesh** reads each mesh file with `process=True`, which merges exactly
   identical vertices and removes zero-area faces before any data enters
   Blender. This is the primary geometry cleanup step and can significantly
   reduce vertex count for VTK-tessellated CSG geometry.
2. **bpy** creates Blender mesh objects from the cleaned vertex/face arrays,
   assigns Principled BSDF materials (cycling through a 10-colour palette of
   steel, brass, copper, and matte variants), and adds a **Weld modifier**
   (secondary duplicate-vertex merge at a configurable distance threshold).
3. A shared **Geometry Nodes** group (`PhiCutaway`) is built programmatically:
   it computes `phi = atan2(Y, X)` per face, evaluates whether each face is
   inside `[phi_min, phi_max]`, and deletes the outside faces. A
   `Merge by Distance` node at the start of the GN chain handles any seam
   duplicates from CSG tessellation boundaries.
4. The `.blend` file is saved with `bpy.ops.wm.save_as_mainfile()`.

bpy and VTK are **never imported in the same Python process** (each subcommand
uses lazy imports), so there is no runtime conflict between the two OpenGL
stacks.

---

## Troubleshooting

**"No sub-detectors found at depth=1"**
> Try `--depth 2`. Some ddsim geometries wrap all detectors inside a single
> top-level assembly before placing them in the world.

**Conversion produces an empty file or crashes**
> Some GDML solid types (e.g. complex parametrized volumes) may not be fully
> supported by pyg4ometry's mesh engine. The `split` step still works; you
> can try loading the split GDML directly in Geant4/GATE for verification.

**Build fails with "Could not find antlr4" or similar**
> Ensure you are building the Docker image (not installing locally). The
> `requirements.txt` pins `antlr4-python3-runtime` to a compatible 4.x version.

**`blender-scene` exits with "No mesh files found"**
> Run `split-convert` first to generate mesh files in the output directory.
> Check that `--format` matches the format used in the convert step (default:
> `gltf`).

**Phi cutaway not updating when I change `PhiCutawayControl` properties**
> In Blender, after changing a custom property that drives Geometry Nodes,
> press **Alt+A** (Play Animation) briefly to force a dependency-graph update,
> or add a small keyframe. This is a known Blender behaviour with GN drivers.

**Weld modifier merging too much / too little geometry**
> Adjust the threshold in **Properties → Modifiers → Weld → Merge Distance**.
> The default (1e-4 mm = 0.1 µm) is conservative. For coarser geometry
> use `0.001` mm; for very fine structures use `1e-6` mm or `0`.

**Scene is very slow to interact with in Blender**
> The Weld + PhiCutaway modifiers are evaluated in real time. For very complex
> geometries, apply the Weld modifier (**Properties → Modifiers → ▼ → Apply**)
> to bake it into the mesh. You can also hide sub-detectors you are not
> currently working with (H key in the viewport, or the eye icon in the
> outliner).

---

## Web viewer (interactive 3D walkthrough)

`web/` is a browser-based, third-person 3D walkthrough of the detector built with
React Three Fiber (three.js) and Vite. It loads the committed sub-detector GLTFs,
lights them with a studio HDRI in real time, and — for the "full Cycles render"
look — displays **Cycles lighting baked into the geometry**.

### Controls

- **Click** the scene to capture the mouse (pointer lock); **Esc** releases it.
- **WASD** move · **mouse** look · **Shift** run · **Space** jump.
- **F** toggles free-fly / noclip (Space = up, C / Ctrl = down) so you can rise
  above the multi-metre detector.
- **Scroll** zooms; the side panel toggles per-sub-detector visibility.

### Run locally

```bash
cd web
npm install
npm run dev          # http://localhost:5173/ddgeoviztools/
```

This uses the raw GLTFs with real-time studio lighting — no Blender required.

### Lighting

The metal reads through **real-time image-based lighting** (an HDRI-style
environment + AgX tone-mapping + bloom + soft shadows) — the correct way to render
metal, whose look is view-dependent and *cannot* be baked. On top of that, Blender
**Cycles bakes the soft, ray-traced ambient occlusion** into the geometry (vertex
colours / glTF `COLOR_0`), which is view-independent and adds the soft
contact-shadow feel. The AO bake is headless and lives in the deploy pipeline:

```
committed GLTF  ->  blender-scene (.blend)  ->  Cycles AO bake  ->  detector_baked.glb
```

```bash
# from web/ (needs Docker; builds the ddgeoviztools image on first run)
npm run bake         # -> web/public/baked/detector_baked.glb (palette PBR + baked AO)
npm run dev          # the viewer now uses the baked geometry + AO
```

Tune samples with `BAKE_SAMPLES` (default 128), e.g. `BAKE_SAMPLES=256 npm run bake`.

### Build / deploy

`npm run build` produces a static site in `web/dist`. The
[`web-deploy`](.github/workflows/web-deploy.yml) workflow runs the whole pipeline
on every push — bake (cached on its inputs), then build — and deploys to GitHub
Pages. **One-time setup:** repo **Settings → Pages → Source = "GitHub Actions"**
(and, to deploy from a non-default branch, allow it under **Settings →
Environments → github-pages**). The site serves at
`https://<user>.github.io/ddgeoviztools/`.

### How the bake reaches the browser

`scripts/bake_lightmaps.py` applies modifiers and Cycles-bakes ambient occlusion
into each sub-detector's vertex colours, keeping the scene's PBR materials, then
exports one Draco-compressed `detector_baked.glb` (decoded by the decoder shipped in
`public/draco/`). The web build sets `__BAKED__` when `web/public/baked/manifest.json`
is present; if absent (e.g. plain `npm run dev` with no bake), the viewer falls back
to the raw GLTFs with the same real-time lighting.
