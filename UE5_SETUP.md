# ColliderVis — UE5 Editor Setup Guide

This guide covers everything you need to do **inside the Unreal Engine 5 editor**
after opening the project for the first time. The C++ code handles lighting,
atmosphere, and game logic automatically at runtime — your job is to wire up the
input assets, materials, and packaging settings described here.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Open & Compile](#2-open--compile)
3. [Create Input Assets](#3-create-input-assets)
4. [Create Materials](#4-create-materials)
5. [Create Data Assets](#5-create-data-assets)
6. [Set Up the Level](#6-set-up-the-level)
7. [Advanced Rendering — Hyperrealism](#7-advanced-rendering--hyperrealism)
8. [Android / Quest 3 Packaging (one-time)](#8-android--quest-3-packaging-one-time)
9. [VR Mode](#9-vr-mode)
10. [Building — Quest 3 & Mac](#10-building--quest-3--mac)

---

## 1. Prerequisites

| Tool | Version | Where |
|------|---------|--------|
| Unreal Engine | 5.4 (or later) | Epic Games Launcher |
| Xcode | 15+ | Mac App Store (for Mac builds) |
| Android Studio | 2023+ | developer.android.com |
| Android NDK | r25b | NDK manager inside Android Studio |
| Java JDK | 17+ | adoptium.net |
| Meta Quest Link | latest | oculus.com/setup (for tethered VR on Mac) |
| adb | bundled with Android Studio | add `~/Library/Android/sdk/platform-tools` to `$PATH` |

---

## 2. Open & Compile

1. Double-click `ColliderVis/ColliderVis.uproject`.
   - If prompted **"missing modules, would you like to rebuild?"** → click **Yes**.
2. Wait for the shader compiler to finish (bottom-right progress bar).
3. If compile errors appear: **Tools → Compile** or press **Ctrl+Alt+F11**.

> The atmosphere, lighting, and fog are all spawned by C++ at `BeginPlay`.
> You do **not** need to place any light actors in the level manually.

---

## 3. Create Input Assets

All input assets live in **Content/Input/**. Create this folder first if it
doesn't exist (right-click Content Browser → New Folder).

### 3a. Input Actions (IA_ assets)

Each IA_ asset defines *what* an action does; the IMC (below) defines *which
key* triggers it.

For each row below: right-click in Content/Input/ → **Input → Input Action** →
name it exactly as shown → set Value Type → Save.

| Asset name | Value Type | Used for |
|---|---|---|
| `IA_Move` | Axis2D (Vector2D) | WASD / left stick locomotion |
| `IA_Look` | Axis2D (Vector2D) | Mouse / right stick look / orbit / VR turn |
| `IA_Jump` | Digital (bool) | Spacebar jump |
| `IA_SwitchMode` | Digital (bool) | Tab / grip — toggle orbit ↔ explore |
| `IA_Zoom` | Digital (bool) | RMB / trigger — zoom orbit |
| `IA_NextEvent` | Digital (bool) | N / face button — next collision event |
| `IA_OpenMenu` | Digital (bool) | Esc — open event file picker |
| `IA_ToggleDetectorMenu` | Digital (bool) | V — show/hide sub-detector panel |
| `IA_DetectorKey` | Axis1D (float) | 1–9 hotkeys for sub-detector toggle |

### 3b. Desktop IMC — `IMC_Default`

Right-click Content/Input/ → **Input → Input Mapping Context** → name `IMC_Default`.

Open it and add these mappings:

| Input Action | Key / Axis | Modifiers |
|---|---|---|
| IA_Move | W | — |
| IA_Move | S | Negate |
| IA_Move | A | Swizzle YXZ, Negate |
| IA_Move | D | Swizzle YXZ |
| IA_Look | Mouse XY 2D-Axis | — |
| IA_Jump | Space Bar | — |
| IA_SwitchMode | Tab | — |
| IA_Zoom | Right Mouse Button | — |
| IA_NextEvent | N | — |
| IA_OpenMenu | Escape | — |
| IA_ToggleDetectorMenu | V | — |
| IA_DetectorKey (×9) | Keys 1–9 | **Scalar** modifier: 1.0, 2.0 … 9.0 respectively |

> The Scalar modifier on IA_DetectorKey encodes which slot was pressed.
> Set it via: Modifiers → + → Scalar → Value = 1.0 (for the "1" key), etc.

### 3c. VR IMC — `IMC_VR`

Right-click Content/Input/ → **Input → Input Mapping Context** → name `IMC_VR`.

| Input Action | Controller input | Notes |
|---|---|---|
| IA_Move | Left Thumbstick 2D-Axis | left stick locomotion |
| IA_Look | Right Thumbstick 2D-Axis | turn (first-person) / orbit (orbit mode) |
| IA_SwitchMode | (R) Grip Axis → threshold | set Threshold trigger at 0.7 |
| IA_Zoom | (R) Trigger Axis → threshold | hold to zoom orbit |
| IA_NextEvent | (R) Face Button 1 (A button) | next event |

> Controller key names in UE5's Enhanced Input live under
> **XR Controller (R) / XR Controller (L)** in the key picker.

---

## 4. Create Materials

The C++ actors reference these materials by path. Create them in
**Content/Materials/**.

### 4a. `M_Track` — charged particle track tubes

1. Right-click Content/Materials/ → **Material** → name `M_Track`.
2. Open it. Set **Blend Mode = Opaque**, **Shading Model = Default Lit**.
3. Create two **Material Parameters**:
   - `TrackColor` (Vector parameter) — plug into **Base Color**.
   - `EmissiveIntensity` (Scalar parameter) — multiply with TrackColor → **Emissive Color**.
4. Set **Emissive Boost** to taste (try `EmissiveIntensity × TrackColor × 0.01`).
5. Roughness: constant 0.3. Metallic: constant 0.6.
6. Save and compile.

> High-momentum tracks will have `EmissiveIntensity` up to ~5000.
> Multiply by a small constant (0.005–0.01) before plugging into Emissive
> so you get visible glow without blowing out the image.

### 4b. `M_CaloHit` — calorimeter energy cubes

1. Right-click → **Material** → `M_CaloHit`.
2. **Blend Mode = Translucent** (or Opaque for performance).
   **Shading Model = Unlit** — pure emissive cubes.
3. Add a **Custom Primitive Data** node, index 0 → this is the normalised energy
   (0–1) stored by `ACaloHitActor`.
4. Wire: `CPD[0]` → lerp between dark blue `(0.0, 0.1, 0.5)` and hot white
   `(1.5, 1.2, 0.8)` → **Emissive Color**.
5. Save.

### 4c. `M_MCParticle` — Monte-Carlo truth lines

1. Right-click → **Material** → `M_MCParticle`.
2. **Shading Model = Unlit**.
3. Constant Emissive Color: `(0.6, 0.6, 1.5)` — pale blue-violet.
4. Opacity: 0.7. **Blend Mode = Translucent**.
5. Save.

---

## 5. Create Data Assets

### 5a. `DA_EventDisplayConfig`

1. Right-click Content/ → **Miscellaneous → Data Asset**.
2. Pick class **EventDisplayConfig** → name `DA_EventDisplayConfig`.
3. Fill in:
   - **Python Executable**: `python3`
   - **EDM4HEP Script Path**: absolute path to `Tools/edm4hep_to_json.py`
   - **Track Tube Radius**: 2.0
   - **Energy Emissive Scale**: 50.0
   - **Calo Hit Base Size**: 5.0
   - **World Scale**: 0.1 (converts mm → cm)
   - **Enabled Calo Collections**: add `ECalBarrelHits`, `HCalBarrelHits`
4. Save.

### 5b. `DA_DetectorVisibility`

1. Right-click Content/ → **Data Asset** → **DetectorVisibilityConfig** → name
   `DA_DetectorVisibility`.
2. Add one entry per sub-detector component of your geometry, e.g.:

   | Name | Visible by Default | Hotkey Slot | Actor Tags |
   |------|-------------------|-------------|------------|
   | ECalBarrel | true | 1 | ECalBarrel |
   | HCalBarrel | true | 2 | HCalBarrel |
   | Tracker | true | 3 | Tracker |
   | Solenoid | true | 4 | Solenoid |
   | MuonSystem | true | 5 | MuonSystem |

3. The **Actor Tags** must match the tags that `Tools/ue5_tag_actors.py`
   assigns to your imported geometry actors.

### 5c. `DA_DetectorGeometryManifest`

This is auto-populated by the Python import pipeline (`Tools/blend_to_ue5.py`).
You don't normally create this by hand. See `Tools/README.md` for the import
workflow.

---

## 6. Set Up the Level

1. **File → New Level → Empty Level**.
2. **World Settings** (Window → World Settings):
   - **GameMode Override** → `ColliderVisGameMode`.
   - The atmosphere (fog, lights, post-process) spawns automatically at
     `BeginPlay` — you don't need to place any of them.
3. **Place your imported detector geometry** actors into the level.
   - Use `Tools/ue5_tag_actors.py` to tag them for the visibility system.
4. **Place an `EventDisplayManager` actor** (search in Place Actors panel).
   - Assign **Config** → `DA_EventDisplayConfig`.
   - Assign **Visibility Config** → `DA_DetectorVisibility`.
5. Optional: place a `ColliderVisCineCameraActor` for cinematic mode.
6. **File → Save Current Level** → name it `ColliderVisMain`.
7. **Project Settings → Maps & Modes → Default Maps → Editor Startup Map** →
   set to `ColliderVisMain`.

---

## 7. Advanced Rendering — Hyperrealism

The C++ code already sets up the void atmosphere, Lumen GI, chromatic
aberration, shadow crush, and emissive bloom. The following are **editor-side
additions** that push the renders further.

### 7a. HDRI Sky Light (reflections on metallic detector surfaces)

Without an HDRI the sky light captures the scene itself, which gives flat
reflections. Replace it with a real HDRI:

1. Download a dark space/nebula HDRI from [Poly Haven](https://polyhaven.com)
   (e.g. *starmap_2020*, free).
2. Import it into Content/Textures/ — UE5 will prompt to import as
   **HDR Texture**.
3. In the level, open **World Settings → Sky Light** (or find the spawned sky
   light actor in the Outliner after a PIE run):
   - **Source Type** → `Specified Cubemap`
   - **Cubemap** → your imported HDR texture
   - **Intensity** → 0.05 (the void is dark; sky contribution stays minimal)
4. Click **Recapture** if visible.

### 7b. Bloom Convolution (real lens halos)

The code uses sum-of-gaussians bloom. Bloom convolution uses a real photograph
of a camera lens flare for physically accurate star-burst patterns around track
glow.

1. Download a lens flare texture (search "UE5 lens convolution texture" or use
   Engine Content `Textures/T_LensFlare_Bloom`).
2. In the **Post Process Volume** (spawned actor in Outliner after PIE):
   - **Bloom → Method** → `Convolution`
   - **Bloom → Convolution Kernel** → your lens texture
   - **Bloom → Convolution Size** → 0.003–0.007
3. The emissive particle tracks will now produce star-burst halos.

> To edit the spawned PPV: run PIE, pause, eject (F8), select the volume in
> the Outliner, edit, then use "Keep Simulation Changes" before stopping PIE.
> Or subclass `AColliderVisGameMode` in Blueprint and override `SetupAtmosphere`
> to set the convolution kernel from a UPROPERTY.

### 7c. Ambient Niagara Particles (floating void dust)

A very subtle ambient particle system makes the void feel inhabited rather than
empty. It also catches the emissive light from tracks.

1. **Window → FX → Niagara Editor** to create a new **Niagara System**.
2. Template: **Fountain** → delete the burst, set to continuous.
3. Emitter settings:
   - **Spawn Rate**: 30
   - **Lifetime**: 20–40 seconds
   - **Velocity**: random, magnitude 0.5–3 cm/s
   - **Size**: 0.3–1.5 cm (very small)
   - **Color**: `(0.04, 0.04, 0.12)` — near-black blue emissive
   - **Emissive Multiplier**: 0.05 — barely glowing
   - **Renderer**: Sprite, material = a simple unlit emissive circle texture
4. Place the Niagara System actor in the level, position at origin, set
   **Spawn Radius** to 3000 cm (slightly larger than the detector).

### 7d. Light Functions on Rect Lights

Light functions are animated textures projected by lights. Adding a subtle
noise texture to the key light makes the detector surface feel like it's under
water / in a magnetic field.

1. Create a Material with **Material Domain = Light Function**.
2. Use a **TexCoord** → **Panner** → sample a cloud/noise texture → output to
   **Emissive Color**. Keep values near 1.0 so the light isn't killed.
3. On the key rect light: **Light Function → Light Function Material** → assign
   your material. **Light Function Fade Distance** → 3000.

### 7e. Per-Material Detector Tweaks (after geometry import)

After importing the detector geometry:

1. Select all detector mesh actors.
2. In Details → **Materials**: create **Material Instances** of a
   base detector material with:
   - **Metallic**: 0.8–1.0 (steel, copper, aluminium)
   - **Roughness**: 0.1–0.4 (polished vs. brushed metal)
   - **Base Color**: use the colours from `DA_DetectorGeometryManifest`
3. For cables and insulation: Metallic=0, Roughness=0.7–0.9.
4. **Nanite**: enable on high-poly meshes (select mesh → Details → Nanite →
   Enable). This gives cinematic-quality geometry with no LOD pop.

### 7f. Path Tracer (still images / screenshots)

For publication-quality stills, switch to the Path Tracer:

1. In the viewport: **View Mode** (top-left dropdown) → **Path Tracing**.
2. Wait for convergence (64 samples, set in `DefaultEngine.ini`).
3. **Screenshot**: `Ctrl+F9` → saves a full-resolution PNG.
4. For 4K output: **Project Settings → Engine → General Settings →
   Custom Screenshot Size** → 3840×2160.

To render an animation sequence:
**Cinematics → Movie Render Queue → add your Level Sequence → render settings:
Path Tracer, 128 samples, EXR output**.

### 7g. Color Calibration

The C++ code already applies:
- Shadow crush → blue-black void
- Teal midtone grade
- Warm highlight push (emissive tracks pop)

To further refine, open the spawned Post Process Volume and adjust:
- **Color Grading → Shadows → Gain** — how dark/blue the void goes
- **Color Grading → Highlights → Gain** — warmth of track glow
- **Bloom Intensity** — how much tracks radiate (currently 2.5)
- **Exposure → Min/Max Brightness** — how aggressively the camera adapts

---

## 8. Android / Quest 3 Packaging (one-time)

Do this once in the editor **before** running `build_quest.sh`.

### 8a. Install Android prerequisites

1. **Edit → Preferences → Platforms → Android SDK** → set all four paths:
   - **SDK**: `~/Library/Android/sdk`
   - **NDK**: `~/Library/Android/sdk/ndk/25.2.9519653` (r25b)
   - **JDK**: `/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home`
   - **Android tools** auto-detected from SDK path.
2. UE5 will show green checkmarks when paths are valid.

### 8b. Project Settings → Android

**Edit → Project Settings → Platforms → Android**:

| Setting | Value |
|---|---|
| Minimum SDK Version | 32 (Quest 3 requires API 32) |
| Target SDK Version | 34 |
| Package Name | `com.yourname.collidervis` |
| Application Display Name | ColliderVis |
| Orientation | Landscape |
| Configure the Android Manifest | ✓ checked |
| Enable FullScreen Immersive | ✓ |
| Support arm64 [AArch64] | ✓ checked |
| Support armv7 | unchecked (Quest 3 is arm64 only) |
| Preferred Build Format | gradle |

Scroll to **Build** → **Android Build Sub-Tools**:
- Build Architecture: `arm64`
- Target Texture Format: **ASTC** (required for Quest 3)

Click **Configure Now** if prompted about the manifest.

### 8c. OpenXR / Meta Quest settings

**Edit → Project Settings → Plugins → OpenXR**:
- ✓ Enable OpenXR
- ✓ Enable Hand Tracking Extension

**Edit → Project Settings → Plugins → OpenXR Hand Tracking**:
- ✓ Enable if available

No MetaXR plugin is needed for basic VR. If you want passthrough or scene
understanding, download the **Meta XR Plugin** from the
[Meta Developer Hub](https://developer.oculus.com/downloads/package/unreal-engine-5-integration/).

### 8d. Sign the APK

For sideloading (developer mode), a debug keystore works:

**Project Settings → Platforms → Android → Distribution Signing** →
click **Generate Debug Keystore**. This creates a `debug.keystore` that
allows side-loading without submitting to the Meta store.

---

## 9. VR Mode

### 9a. Testing in Editor (tethered Quest 3)

1. Connect Quest 3 via USB-C or Wi-Fi (Meta Quest Link).
2. In the Quest headset, accept the **Allow Computer Access** prompt.
3. In UE5 editor: **World Settings → GameMode Override** →
   `ColliderVisVRGameMode`.
4. **VR Preview** button (dropdown next to the Play button) → **VR Preview**.
5. Put on the headset — you should see the detector floating in the void.

**Controls in VR:**
| Action | Controller |
|---|---|
| Look around | HMD — just move your head |
| Walk through detector | Left thumbstick |
| Turn in place | Right thumbstick X |
| **Switch to orbit mode** | **Right grip button** |
| Orbit rotation | Right thumbstick (while in orbit) |
| Zoom orbit | Right trigger held (while in orbit) |
| Next event | Right A button |

### 9b. Standalone Quest binary

Build with `./scripts/build_quest.sh`, then:

```bash
# Install via USB
adb install Builds/Quest3/Android_ASTC/ColliderVis-arm64.apk

# Or wirelessly (replace with your Quest IP)
adb connect 192.168.1.42:5555
adb install Builds/Quest3/Android_ASTC/ColliderVis-arm64.apk
```

The app appears in **Unknown Sources** in the Quest library.

---

## 10. Building — Quest 3 & Mac

Both scripts auto-detect the project path relative to themselves. Set
`UE5_ROOT` if your engine isn't in the default location.

### Quest 3 (Android standalone APK)

```bash
# Default Shipping build
./scripts/build_quest.sh

# Development build (includes debug symbols, console, stat commands)
BUILD_CONFIG=Development ./scripts/build_quest.sh

# Custom engine path
UE5_ROOT="/Volumes/SSD/UE_5.4" ./scripts/build_quest.sh
```

Output: `Builds/Quest3/Android_ASTC/ColliderVis-arm64.apk`

### Mac (standalone .app)

```bash
./scripts/build_mac.sh
```

Output: `Builds/Mac/Mac/ColliderVis.app`

### Run Mac build in VR (tethered Quest 3)

```bash
# Quest Link must be running and headset connected first
"Builds/Mac/Mac/ColliderVis.app/Contents/MacOS/ColliderVis" \
    -game /Script/ColliderVis.ColliderVisVRGameMode
```

---

## Quick-Reference: What the C++ does automatically

So you know what you **don't** need to do in the editor:

| Automatic | Where |
|---|---|
| Spawn post-process volume (Lumen, bloom, color grade, vignette) | `ColliderVisGameMode::SetupAtmosphere` |
| Spawn exponential height fog (two-layer ethereal void) | same |
| Spawn key / fill / rim / under-glow rect lights | same |
| Spawn sky atmosphere + near-zero directional light | same |
| Parse EDM4HEP ROOT files → JSON | `AEventDisplayManager` |
| Spawn track / calo hit / MC particle actors per event | same |
| Auto-focus cinematic camera on event centroid | `AColliderVisCineCameraActor::Tick` |
| VR first-person locomotion + orbit mode | `AColliderVisVRPawn` |
| Sub-detector visibility hotkeys 1–9 | `AColliderVisCharacter`, `ADetectorVisibilityManager` |
| Android standalone defaults to VR game mode | `Config/Android/AndroidGame.ini` |
