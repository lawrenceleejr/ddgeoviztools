# Exporting a Meta Quest 3 APK — investigation & guide

_Investigation date: 2026-06-21 (UE 5.8, macOS / Apple Silicon)._

**Short answer:** Yes, an APK is buildable and will boot on Quest 3 — the project
already has most of the *runtime* scaffolding (a VR pawn, a VR game mode, OpenXR,
and a full set of mobile/Quest rendering overrides). What's missing is (1) the
**Android build toolchain**, (2) an **`AndroidRuntimeSettings` packaging block**
(arm64 + Vulkan + "Package for Meta Quest"), and (3) a **mobile look/perf pass** —
the desktop "moody" aesthetic leans on Lumen GI, which does **not** exist on Quest.
This is a real but non-trivial effort; the foundation is ~40% there.

---

## What's already in place ✅

| Piece | Where | Status |
|------|-------|--------|
| VR pawn (HMD camera + motion controllers) | `Source/ColliderVis/ColliderVisVRPawn.{h,cpp}` | Implemented |
| VR game mode (inherits the desktop look, swaps in the VR pawn) | `Source/ColliderVis/ColliderVisVRGameMode.{h,cpp}` | Implemented |
| OpenXR + hand-tracking + XRBase plugins | `ColliderVis.uproject` | Enabled |
| Android **rendering** overrides (Lumen off, forward shading, MSAA 4×, MobileHDR, MobileMultiView, no volumetric fog, pixel density 0.9) | `Config/Android/AndroidEngine.ini` | Done |
| Android **game** override (standalone Quest boots into `AColliderVisVRGameMode`) | `Config/Android/AndroidGame.ini` | Done |
| `DesktopPlatform` excluded on Android (the OS file picker) | `Source/ColliderVis/ColliderVis.Build.cs` | Done |
| VR-friendly menu hook | `ColliderVisVRPawn` → `AColliderVisHUD::ToggleMenu()` | Partial |
| Geometry simplified to ~415 k tris total | `Config/DefaultEngine.ini` note | Done (mobile-feasible) |

So the **code/config that makes the game *run* in VR is already written.** The gaps
are all about *packaging the APK* and *making it look good + run fast on mobile*.

---

## What's missing ❌ (the work to actually ship an APK)

### 1. Android build toolchain (not installed)
There is currently **no Android SDK/NDK** on this machine (`~/Library/Android`
doesn't exist, `adb` isn't on PATH). UE 5.8 needs a specific SDK/NDK/JDK combo.

Install it with the bundled setup script (installs the exact versions UE expects):

```bash
"/Users/Shared/Epic Games/UE_5.8/Engine/Extras/Android/SetupAndroid.command"
```

(or Android Studio + the matching NDK; the script is the supported path). After it
runs, `adb` lives under `~/Library/Android/sdk/platform-tools/`. Verify in-editor:
**Edit ▸ Project Settings ▸ Platforms ▸ Android SDK** should show green checkmarks.

> macOS **can** package Android/Quest builds — you do **not** need Windows.

### 2. `AndroidRuntimeSettings` packaging block (does not exist yet)
There is no `[/Script/AndroidRuntimeSettings.AndroidRuntimeSettings]` section
anywhere in `Config/`. Add it to `Config/DefaultEngine.ini` (or set the equivalents
in Project Settings ▸ Platforms ▸ Android). Minimum for a Quest 3 sideload:

```ini
[/Script/AndroidRuntimeSettings.AndroidRuntimeSettings]
PackageName=com.utk.collidervis
MinSDKVersion=29
TargetSDKVersion=32            ; Meta requires target 32 (Android 12L) for Quest
bBuildForArm64=True
bBuildForArmV7=False
bBuildForX8664=False
bSupportsVulkan=True           ; Quest 3 is Vulkan; turn OpenGL ES OFF
bSupportsOpenGLES=False
bPackageForMetaQuest=True      ; (older UE: bPackageForOculusMobile) — the key Quest flag
bFullScreen=True
```

You must also **accept the Android SDK license** (Project Settings ▸ Android ▸
"Accept SDK License" button) before the build will run.

### 3. (Recommended) Meta XR plugin
Stock OpenXR is enough to **sideload and boot** a basic standalone build. For
production Quest features — passthrough, accurate controller/hand models, Meta's
performance tooling, and Quest **Store** submission — install Meta's **Meta XR
plugin** (from Fab / Meta's site) and enable it alongside/instead of stock OpenXR.
Not required for a dev sideload; required for store-grade polish.

### 4. Texture/cook flavor
Android cooks need a compressed-texture flavor. Use **ASTC** for Quest 3.

---

## Build & deploy (once 1–2 above are done)

**From the editor:** Platforms ▸ **Android (ASTC)** ▸ *Package Project* → pick an
output folder → produces `ColliderVis-arm64.apk`.

**From the command line (Mac):**
```bash
"/Users/Shared/Epic Games/UE_5.8/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun \
  -project="/Users/leejr/Work/ddgeoviztools/ColliderVis/ColliderVis.uproject" \
  -platform=Android -cookflavor=ASTC \
  -clientconfig=Development -build -cook -stage -package -archive \
  -archivedirectory="/Users/leejr/Work/ddgeoviztools/ColliderVis/Builds/Quest3"
```

**Sideload to the headset** (Quest 3 in Developer Mode, USB connected, "Allow USB
debugging" accepted in-headset):
```bash
adb install -r .../ColliderVis-arm64.apk
# launch: Library ▸ "Unknown Sources" ▸ ColliderVis
```

---

## ⚠️ Realistic assessment — the hard part isn't the APK, it's the look & perf

The project was built for **desktop Metal/Lumen**. The Android config already turns
off everything Quest can't do, but turning those features off has consequences:

1. **No Lumen GI on Quest.** The whole "moody, awe-inspiring" look (see
   `collidervis-game-polish` notes) is driven by Lumen global illumination + Lumen
   reflections + emissive bounce + the −2 auto-exposure. On mobile forward shading
   those are gone, so the hall will look **flat and dark**. You'll need to re-light
   for mobile: more/brighter direct movable lights, a stronger SkyLight, and likely
   **baked lighting** for the static hall. Caveat: the merged/Geometry-Script cut
   meshes and the simplified detector likely have **no lightmap UVs**, so baking
   needs generated UVs first (or commit to all-dynamic mobile lighting).

2. **Translucency is the #1 perf risk.** Calo hits (~230 translucent instanced
   cubes), the MC-particle material, and the **frosted translucent elevator floor**
   (just added) are all translucent. Translucent overdraw is expensive on Quest's
   tiled mobile GPU, especially at 2064×2208 ×2 eyes @ 72–90 Hz. Expect to: make
   calo hits **opaque/masked** for the Quest build, and reconsider the translucent
   floor (the "or make it opaque" fallback is the *right default on mobile*).

3. **Dynamic lights are costly on mobile forward.** The desktop rig (key/rim/fill +
   ring rims + 2 god-lights, several with volumetric scattering) needs trimming to a
   handful of lights, shadows on at most one or two.

4. **Post-process** — bloom survives on mobile; film grain / heavy auto-exposure /
   vignette are limited or off. VR generally wants **fixed exposure** (lock it), not
   the desktop's auto-exposure that the dark hall fights.

5. **Input/UI not finished for VR.** `IMC_VR` exists but its XR controller bindings
   were flagged as needing manual wiring (build-script TODO), and the HUD is
   screen-space (needs a world-space/VR widget). Locomotion (teleport vs smooth) and
   comfort (vignette on turn) aren't implemented yet.

**Bottom line:** budget the effort as
- ~½ day: toolchain + `AndroidRuntimeSettings` + first APK that boots (mostly mechanical).
- Several days: a mobile **lighting/material/perf pass** so it looks good and holds
  frame rate, plus finishing VR input/UI/locomotion.

A pragmatic milestone order: (a) get *any* APK booting in VR with the current scene
(ugly but proves the pipeline), (b) profile with `stat unit` / Meta's OVR Metrics
Tool, (c) do the mobile look/perf pass, (d) add the Meta XR plugin if Store-bound.
