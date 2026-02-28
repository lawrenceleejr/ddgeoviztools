# ddgeoviztools

CLI tools for working with ddsim/DD4hep GDML detector geometries:

1. **Split** — divide a monolithic GDML into one file per sub-detector system.
2. **Convert** — convert a GDML file to OBJ, GLTF, or VTP for visualization.
3. **Split-convert** — do both in one command.

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
