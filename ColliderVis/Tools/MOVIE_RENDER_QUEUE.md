# Movie Render Queue — Non-Realtime Lumen Renders (ColliderVis, macOS / Apple Silicon)

How to produce clean, high-quality "ray-traced-look" stills and sequences of the
MAIA detector display on this Mac. On Apple Silicon / Metal, the true hardware
**Path Tracer is unavailable**, so our highest-quality offline path is the
**Movie Render Queue (MRQ)** driving **Lumen at HWRT/high quality** with heavy
temporal + spatial sampling and warmup. This matches the cinematic grade baked
into `AColliderVisGameMode::SetupPostProcessAndFog()` (PIE and MRQ share the
PostProcessVolume), so renders look like PIE but cleaner and noise-free.

> Path-tracer note: the scene is kept path-tracer-friendly (emissive tracks,
> physical lights, Lumen reflections). For a *true* Path Tracer pass, open this
> project on a **Windows machine with an RTX GPU**, enable `r.PathTracing=1` in
> the MRQ "Path Tracer" setting, and re-render. Nothing in the scene needs to
> change — only the platform.

---

## 0. One-time setup

1. **Enable plugins** (Edit → Plugins, restart editor):
   - *Movie Render Queue*
   - *Movie Render Queue Additional Render Passes* (for object IDs / depth, optional)
2. **Project rendering settings** (Project Settings → Engine → Rendering):
   - Global Illumination = **Lumen**
   - Reflections = **Lumen**
   - Lumen → **Use Hardware Ray Tracing when available = On**
   - Lumen → Ray Lighting Mode = **Hit Lighting for Reflections** (best quality)
   - Shadow Map Method = **Virtual Shadow Maps**
   - **Extend default luminance range** = On (for EXR/HDR output)
   These persist in `Config/DefaultEngine.ini`.

---

## 1. Open Movie Render Queue

- Window → Cinematics → **Movie Render Queue**.
- For a **sequence**: create/open a Level Sequence (e.g. a flythrough of the
  detector or an event-animation take) and add it with **+ Render**.
- For a **single still**: make a 1-frame Level Sequence containing a
  `CineCameraActor` framing the detector, add it, and set the output range to a
  single frame. (You can also just render frame 0 of any sequence.)

Click the **Settings** entry on the job to open the config; add the settings below.

---

## 1b. Cameras (spawned by AColliderVisGameMode)

`AColliderVisGameMode::SetupCinematicCameras()` spawns a dramatic camera set at
BeginPlay (gated by `bSpawnCinematicCameras`, default ON). All use wide-angle FOV
and shallow physical depth of field (per-camera DoF via `DepthOfFieldFstop` /
`FocalDistance` / `SensorWidth`), and lens flare scaled up on the movers.

**Static "money shots":**
- `Cam_Hero_LowWide` — low, very wide (FOV 95, f/2.0), looking up at the core.
- `Cam_Establish_ThreeQuarter` — high 3/4 establishing (FOV 85, f/2.2).
- `Cam_Profile_Detail` — side profile, tightest + very shallow (FOV 70, f/1.8).
- `Cam_TopDown_God` — straight-down ultrawide (FOV 100, f/4.0).

**Animated (driven in `Tick()`, lens flare 0.7–0.9):**
- `Cam_Anim_Orbit` — slow 24 s wide orbit, low, bobbing height.
- `Cam_Anim_Dolly` — 18 s push-in / pull-back along −X with a slow side arc.
- `Cam_Anim_Crane` — 30 s crane sweeping low→high while orbiting the far side.

Notes for the orchestrator:
- These are **`ACameraActor`s** (Engine module, no `CinematicCamera` dep). For
  the highest-fidelity offline look you can convert/duplicate them as
  `CineCameraActor`s in-editor (adds physical filmback + focus tracking). To do
  that in code instead, add `"CinematicCamera"` to `ColliderVis.Build.cs`
  (orchestrator-owned file) and swap the spawn type.
- The Tick-driven animation is for **PIE preview / quick capture**. For final
  renders, author the same moves as **Level Sequences** (camera-cut track +
  transform keys, or attach to a `CameraRig_Rail` / `CameraRig_Crane`) so MRQ can
  render them deterministically with motion blur. The spawned cameras' start
  transforms and the move parameters in `Tick()` are the reference for keyframes.
- For a hands-off attract/capture session, set `bUseCinematicCameraAsView = true`
  on the GameMode to make `Cam_Anim_Orbit` the live PIE view target at BeginPlay.
- `CameraTargetLocation` (default (0,0,150)) is the look-at / orbit pivot; point
  it at the collision region or a sub-detector of interest.

---

## 2. Recommended MRQ config (Lumen high-quality stills/sequences)

### Output
- **Output Resolution**: `3840 x 2160` (4K). For posters bump to `7680 x 4320`.
- **Output Directory**: `{project_dir}/Saved/MovieRenders/{date}/`
- **File Name Format**: `ColliderVis_{sequence_name}_{frame_number}`

### Image output format (pick one)
- **.EXR (recommended for stills / grading)**: `EXR Sequence`
  - Compression: `PIZ` (lossless) or `ZIP`.
  - Output is linear HDR (16/32-bit) — best for any later color work.
  - Enable extended luminance range (step 0 above) so highlights aren't clipped.
- **.PNG (recommended for quick previews / final deliverables)**: `PNG Sequence`
  - 8-bit, tone-mapped with the in-scene grade applied. What-you-see-in-PIE.

### Anti-aliasing  (the quality knob)
Add **Anti-aliasing** setting:
- **Spatial Sample Count**: `8` (stills) / `4` (sequences — cheaper per frame)
- **Temporal Sample Count**: `8` (stills) / `8–16` (motion-blur sequences)
- **Override Anti-Aliasing Method**: `None` (let temporal/spatial samples resolve)
  - or `TSR` if you keep a low sample count and want TSR to clean up.
- **Engine Warm Up Count**: `64` (lets Lumen GI/reflections converge before capture)
- **Render Warm Up Frames**: `On`
- **Use Camera Cut for Warm Up**: `On`

> Total accumulated samples per output frame = Spatial × Temporal.
> `8 × 8 = 64` is a strong, low-noise still. Raise both for hero frames.

### Console Variables  (force Lumen to offline quality)
Add **Console Variables** setting and paste:
```
r.Lumen.HardwareRayTracing 1
r.Lumen.Reflections.HardwareRayTracing 1
r.Lumen.TraceMeshSDFs 1
r.LumenScene.Lighting.Quality 4
r.Lumen.ScreenProbeGather.Quality 4
r.Lumen.Reflections.Quality 4
r.Lumen.Reflections.SmoothBias 0.1
r.LumenScene.Radiosity.Quality 4
r.RayTracing.Shadows 1
r.MotionBlurQuality 4
r.DepthOfFieldQuality 4
r.Tonemapper.Quality 5
r.VolumetricFog 1
r.VolumetricFog.GridPixelSize 4
r.VolumetricFog.GridSizeZ 256
```
(The `VolumetricFog.*` lines sharpen the god-ray shafts from the warm key/rim
rig set up in `SetupDefaultLightRig()`.)

### High Resolution (optional, for very large stills)
- Use **High Resolution** tiling (e.g. `2x2`) only if you exceed GPU memory at
  8K. Overlap `0.1`. Not needed at 4K on most Apple Silicon GPUs.

### Game Overrides
- Add **Game Overrides**: Game Mode Override = leave default
  (`AColliderVisGameMode`) so the in-game PostProcessVolume + warm light rig
  spawn exactly as in PIE. **Cinematic Quality = Cine (Epic)**.

---

## 3. Render

- Click **Render (Local)**.
- The editor switches to PIE-style rendering, runs the warmup frames, then
  accumulates samples per frame and writes to the output directory.
- A 4K still at 8×8 samples + 64 warmup typically takes seconds-to-minutes per
  frame on Apple Silicon; sequences scale linearly with frame count.

---

## 4. Quick preset summary

| Use case            | Res    | Spatial | Temporal | Warmup | Format |
|---------------------|--------|---------|----------|--------|--------|
| Hero still / poster | 4K–8K  | 8       | 8        | 64     | EXR    |
| Web/preview still   | 4K     | 4       | 4        | 32     | PNG    |
| Flythrough sequence | 4K     | 4       | 8        | 64     | PNG/EXR|
| Event animation     | 4K     | 4       | 16       | 64     | EXR    |

---

## 5. Saving the config as a reusable preset

In the MRQ config window: **... (top-right) → Save As Preset** →
`MRQ_ColliderVis_Lumen4K`. It is stored under
`{project}/Saved/MovieRenderPipeline/Presets/` (or Content if you choose) and
can be loaded on every future job. Commit a copy if you want it version-tracked.

---

## 6. True Path Tracer (future, Windows/RTX only)

On a Windows box with an NVIDIA RTX GPU:
1. Project Settings → Rendering → **Support Hardware Ray Tracing = On**, restart.
2. In the MRQ config, add the **Path Tracer** setting (replaces the default
   deferred renderer for that job).
3. Add Console Variables: `r.PathTracing 1`, and raise
   `MRQ → Anti-aliasing → Spatial Sample Count` to `64–256` (the path tracer
   accumulates these as path-tracing samples per pixel).
4. Output EXR. Expect much longer render times but reference-quality GI,
   reflections, and soft shadows from the same warm key/fill/rim rig.

No scene/source changes are required — the lighting, materials, and grade are
already authored to be physically plausible.

---

## 7. Headless command-line render (orchestrator path) — `Tools/render_lumen_mrq.sh`

The interactive MRQ window (sections 1–5) is the artist path. For **automated /
batch** renders (orchestrator runs it with the editor closed), use the scripted
two-step pipeline. This was verified against the UE 5.8 engine source
(`MovieRenderPipelineCommandLine.cpp`): a command-line MRQ render **requires**
both a Level Sequence **and** a config/queue asset — there is *no* pure-flags
path that fabricates a config. So we generate the assets once, then render.

### Step 1 — build the MRQ config + a still sequence (one-time, idempotent)
```
"/Users/Shared/Epic Games/UE_5.8/Engine/Binaries/Mac/UnrealEditor-Cmd" \
  "/Users/leejr/Work/ddgeoviztools/ColliderVis/ColliderVis.uproject" \
  -run=pythonscript \
  -script="/Users/leejr/Work/ddgeoviztools/ColliderVis/Tools/make_mrq_config.py" \
  -unattended -nosplash
```
Creates:
- `/Game/Cinematics/MRQ_ColliderVis_Lumen4K` — `UMoviePipelinePrimaryConfig`
  (Output 4K + PNG, Deferred pass, AA 8×8 spatial/temporal + 64 engine warmup,
  Game Overrides cine-quality, and the Lumen console variables from §2).
- `/Game/Cinematics/LS_ColliderVis_Still` — a 1-frame Level Sequence with a
  **spawnable CineCamera** framing the detector origin + a camera-cut track, so
  a hero still renders even though the project ships no authored sequence yet.

To switch PNG→EXR or change resolution/samples, edit the tunables at the top of
`Tools/make_mrq_config.py` (`USE_EXR`, `RES_X/Y`, `SPATIAL_SAMPLES`, …) and re-run.

### Step 2 — render headless
```
chmod +x Tools/render_lumen_mrq.sh      # one-time
Tools/render_lumen_mrq.sh               # default hero still
# or do both steps at once:
Tools/render_lumen_mrq.sh --make-config
# custom sequence / output / engine:
Tools/render_lumen_mrq.sh --seq /Game/Cinematics/LS_MyFlythrough --out /abs/renders
```
The script invokes `UnrealEditor-Cmd ColliderVis.uproject /Game/Maps/ColliderVisMain
-game -LevelSequence=… -MoviePipelineConfig=… …`. MRQ auto-starts when the map
finishes loading and the process exits 0 on success. Frames land in the config's
Output Directory (`{project_dir}/renders/`, i.e. `<project>/renders/`).

> Run with the **interactive editor closed** — two editors fight over the project
> lock and shader DDC. A real (small) RHI window is spawned (`-windowed -resx=1280
> -resy=720`); do **not** add `-nullrhi` to the render step — Lumen needs the GPU.
> `-nullrhi` is only used for the Python config-build step (no rendering there).
