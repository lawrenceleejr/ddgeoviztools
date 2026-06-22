# Detector Geometry Import Workflow: Blender → UE5

## Step 1 — Run the Blender pipeline (if not done already)

```bash
# In ddgeoviztools: split GDML → per-subdetector GLTF
docker run --rm -v /data:/data ddgeoviztools split-convert \
    /data/detector.gdml /data/gltf_out/

# Build a .blend file with phi cutaway, bevel, and PBR materials
docker run --rm -v /data:/data ddgeoviztools blender-scene \
    /data/gltf_out/ /data/detector.blend
```

## Step 2 — Export the .blend to UE-ready GLTF + manifest.json

Uses the ddgeoviztools Docker image (no local Blender needed). This exports per-sub-detector
GLTF **plus** the Blender light rig and cameras into `manifest.json`:

```bash
scripts/blend_to_ue5_export.sh /data/detector.blend -o /tmp/ue5_meshes
```

Output:
```
/tmp/ue5_meshes/
    ECalBarrel.gltf, HCalBarrel.gltf, Solenoid.gltf, ...
    manifest.json          # sub_detectors[] + lights[] + cameras[]
```

The phi **cutaway** is already baked into the exported mesh geometry, so it transfers
automatically — nothing extra to do in UE.

## Step 3 — Build all UE content automatically

Steps 3–7 of the old manual workflow (import GLTF, create materials / input / data assets /
blueprints, build the level, tag actors, spawn the Blender lights) are now done by one
idempotent script: **`Tools/ue5_build_content.py`**.

Run it inside the editor from the editor's Python console:

```python
import sys; sys.path.append(r"<repo>/ColliderVis/Tools")
import ue5_build_content as b
b.build({"manifest_dir": "/tmp/ue5_meshes"})
```

or headless:

```bash
UnrealEditor-Cmd ColliderVis.uproject -run=pythonscript \
    -script="<repo>/ColliderVis/Tools/ue5_build_content.py --manifest-dir /tmp/ue5_meshes"
```

It creates (idempotently — safe to re-run):

| Output | Path |
|--------|------|
| Detector meshes (Nanite, no-collision, tagged) | `/Game/Detector/*` |
| Materials `M_Track`, `M_CaloHit`, `M_MCParticle`, `M_DetectorGeometry` + per-sub-detector MICs | `/Game/Materials/*` |
| Input `IA_*`, `IMC_Default`, `IMC_VR` (keys + modifiers) | `/Game/Input/*` |
| `DA_EventDisplayConfig`, `DA_DetectorVisibility`, `DA_DetectorGeometryManifest` | `/Game/Data/*` |
| `BP_EventDisplayManager`, `BP_CineCamera`, `BP_ColliderVisCharacter` | `/Game/Blueprints/*` |
| `WBP_Options`, `WBP_DetectorRow` (stubs — layout is manual, see UE5_SETUP §7) | `/Game/UI/*` |
| Level `ColliderVisMain` (meshes + Blender lights + managers, set as startup map) | `/Game/Maps/*` |

Watch stdout for `COLLIDERVIS_BUILD_RESULT={...}` (machine-parseable summary) and any
`MANUAL TODO` lines.

> `ue5_tag_actors.py` (tag-only) is kept for re-tagging an already-populated level; the full
> builder above supersedes it for a fresh setup.

## Step 4 — Finish the manual bits

The builder reports these as TODOs (they can't be reliably scripted):

1. **Example character model** — add the **Third Person** feature pack
   (*Content Browser → Add → Add Feature or Content Pack → Third Person*). The character
   auto-binds `SKM_Quinn_Simple` + `ABP_Quinn` on the next compile.
2. **WBP_Options / WBP_DetectorRow** — build the UMG layout + button wiring (UE5_SETUP §7).
3. **IMC_VR** — finish any XR controller bindings your VR plugins require (UE5_SETUP §3c).

## Verification

- [ ] `COLLIDERVIS_BUILD_RESULT` reports `"ok": true`
- [ ] `/Game/Detector/*` meshes present; one selected shows **Nanite Enabled**
- [ ] `ColliderVisMain` opens: detector at origin with the cutaway open, lit by `Light_*`
      actors (the Blender rig), `EventDisplayManager` + `DetectorVisibilityManager` placed
- [ ] PIE: third-person Mannequin spawns and is controllable (WASD), **RMB zooms in** (arm +
      FOV), keys 1–9 toggle sub-detectors
- [ ] `stat Nanite` shows virtual geometry active
