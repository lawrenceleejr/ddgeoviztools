# ColliderVis — Godot 4 Edition

`ColliderVisGodot/` is a fully self-contained, **runnable** port of the
ColliderVis event display. Unlike the UE5 project (which requires an
Epic-licensed engine install and manual editor setup), this one needs zero
editor work: every light, material, camera, menu, and post-process effect is
built procedurally at startup. Open it and it works.

## Quick start

```bash
# 1. Get Godot 4.6+ (one ~70 MB download, no account needed)
#    https://godotengine.org/download

# 2. Run
godot --path ColliderVisGodot
```

Or download the **ready-to-run macOS app** from GitHub Actions: every push
builds the `ColliderVis-macOS-dmg` artifact — a DMG with the universal
ad-hoc-signed app, an Applications shortcut, and a README covering the
one-time Gatekeeper step:

```bash
xattr -cr /Applications/ColliderVis.app
open /Applications/ColliderVis.app
```

(A bare `ColliderVis-macOS.zip` artifact is also published.)

## What you get

- **Splash screen + logo**, generated at runtime (no binary assets in git).
- **Detector geometry** loaded at runtime from glTF (`assets/detector/*.gltf`,
  the output of `./run.sh split-convert`). Sub-detectors get PBR
  metal/crystal materials matched by name — same palette as the Blender
  pipeline.
- **High-quality lighting**: **baked VoxelGI** — the detector and hall are
  voxelized at startup (~15 s, re-baked when new geometry loads) for
  high-quality bounced light and rough metal reflections, plus a hall-wide
  reflection probe for sharp speculars. SSAO + SSIL, screen-space
  reflections, volumetric god-rays from the practical lights, HDR bloom,
  AgX filmic tonemapping. (`--gi=sdfgi` skips the bake and uses real-time
  SDFGI instead; it's also the automatic fallback if the bake fails.)
- **Cinematic camera stack**: depth-of-field bokeh that tracks the orbit
  distance, screen-space lens flares (ghosts, halo, anamorphic streaks),
  camera motion blur, chromatic aberration, vignette, film grain,
  inertia-smoothed orbit with idle auto-orbit drift.
- **Event display**: charged tracks as momentum-glowing emissive tubes
  (orange = +, cyan = −), calorimeter hits as energy-colored cubes,
  MC truth lines. The interaction point lights the detector interior.
- **Phi cutaway** (the Blender pipeline's signature feature) implemented in
  the detector shader — toggle with `C`, resize with `[` / `]` or the menu
  slider.
- **Third-person mode**: a rigged, animated explorer at true human scale
  (~1.8 m — a real size reference against the 9 m detector): GDQuest's
  "Mannequiny" (CC-BY 4.0, attributed on the in-game credits section and in
  `assets/character/CREDITS_GDQUEST.txt`), cross-blended idle/run/jump/land
  clips with playback speed matched to velocity. If the model file is
  removed, a procedurally built hard-hat-and-hi-vis "cavern physicist"
  (with a glowing atom emblem) takes its place.
- **Full in-game UI** (`Esc`): open event files (native OS file picker),
  jump to any event index, reco/truth particle listings, per-sub-detector
  visibility toggles, camera/cutaway controls, and a **settings panel**:
  live FPS + GPU/driver readout, resolution presets and fullscreen, render
  scale, quality presets (Performance/Balanced/Quality), light brightness,
  depth of field, individual lens-effect toggles (flares, motion blur,
  chromatic aberration, grain, vignette), and an event-display on/off
  switch so you can view the bare detector.
- **Stage**: the detector floats in a smooth, softly lit dome over an
  "infinite" glass floor at the beam plane (y = 0) — in third-person mode
  you walk right up to the interaction point. Events propagate from the IP: trajectories draw on along their
  path length at fixed speed, and calorimeter hits light up when that
  front reaches them.
- On macOS the app runs on **native Metal** (Godot's default on Apple
  Silicon since 4.4) — check the GPU/driver line in Settings to confirm.

## Controls

| Input | Action |
|---|---|
| LMB drag / wheel / MMB | orbit / zoom / pan |
| **Tab** | cycle camera: Orbit → Fly → Third person |
| WASD (+ Q/E, Shift) | move in Fly / Third-person modes |
| **Space** | **next event** (jump, in third-person mode) |
| B | previous event |
| Esc | menu (or release mouse) |
| 1–9 / 0 | toggle sub-detectors / show all |
| C, [ , ] | cutaway on/off, shrink/grow opening |
| H | hide UI |

## Loading your own events

**In-game:** Esc → *Open event file…* — pick either:

- a `event_NNNN.json` produced by `ColliderVis/Tools/edm4hep_to_json.py`
  (the whole directory is loaded so Space cycles through it), or
- an **EDM4HEP/key4hep `.root` file directly** — ColliderVis converts it on
  the fly via `edm4hep_to_json.py`, which needs `python3` with
  `pip install uproot awkward`. If the converter script isn't found
  automatically, point the `COLLIDERVIS_CONVERTER` environment variable at it.

**From the CLI:**

```bash
godot --path ColliderVisGodot -- --events=/path/to/jsons_or_file.root
```

Three bundled sample events (`events/event_*.json`, generated by
`tools/make_sample_event.py`) load automatically on startup.

## Loading your own detector

Three ways, all taking the glTF output of `./run.sh split-convert`
(one .gltf per sub-detector):

- **In-game**: Esc → *Load detector folder…* — picks a directory, swaps the
  geometry live, and re-bakes the GI around it.
- CLI: `--geometry=/path/to/gltf_dir`
- Drop the files into `assets/detector/` (bundled default).

## Headless rendering (no GPU needed)

The whole app runs on Mesa's software Vulkan driver — this is how CI
verifies every build:

```bash
sudo apt-get install mesa-vulkan-drivers xvfb   # Linux
xvfb-run -a godot --path ColliderVisGodot -- --screenshot=out.png --frames=150
```

Useful flags (after `--`): `--events=…`, `--geometry=…`, `--hide=Group1,Group2`,
`--no-event`, `--no-splash`, `--hud`, `--frames=N`.

## CI

`.github/workflows/godot-build.yml` builds, on every push that touches
`ColliderVisGodot/`:

- **macOS app** (universal, ad-hoc signed) as a zip and a DMG
- **Linux binary**, then boots it under Xvfb + lavapipe and renders a
  verification frame (`verification-render` artifact)
- **Meta Quest APK** (`ColliderVis-Quest`): Android XR export with the
  [Godot OpenXR Vendors](https://github.com/GodotVR/godot_openxr_vendors)
  plugin (downloaded by CI; gitignored locally). Sideload with
  `adb install ColliderVis-Quest.apk` (developer mode). In the headset:
  left stick glides, right stick snap-turns 45°; right trigger / A =
  next event, B = previous; left trigger = previous; X = cutaway;
  grip steps an "x-ray" cursor through the sub-detector groups.
  **Y opens the in-VR menu** — a world-space panel you point at with the
  right-hand laser (trigger to click): prev/next event, event display,
  cutaway +/-, brightness & render-scale sliders, per-sub-detector
  toggles, recenter, and **Passthrough (mixed reality)** to see the
  detector floating in your real room. Tuned for smoothness: Mobile
  renderer, 0.7 render scale, dynamic foveation, MSAA 2x.

  **Signing & Meta Horizon store uploads.** The APK is release-signed with
  a fixed, committed keystore (`ColliderVisGodot/release.keystore`, alias
  and password `collidervis`) so that *every* CI build carries the **same
  signing certificate**. This matters because Meta locks an app to the
  certificate of its first uploaded build — if later builds are signed with
  a different key, the web uploader hangs at *"validating package
  contents"* instead of erroring. (The earlier CI regenerated a random
  keystore each run, so only the very first upload ever went through.) To
  use your own key instead, set the repo secrets `QUEST_KEYSTORE_B64`
  (base64 of your `.keystore`), `QUEST_KEYSTORE_ALIAS`, and
  `QUEST_KEYSTORE_PASS`; they override the committed key. If a Meta app has
  already recorded a *different* certificate from a previous upload, you
  must create a fresh app/release channel to adopt this key — Meta won't
  accept a re-signed build on the existing app. If the web uploader still
  stalls, use Meta's command-line uploader
  (`ovr-platform-util upload-quest-build`), which Meta recommends for
  larger packages and which avoids the flaky web validation step. The CI
  log prints the certificate SHA-256 and `apksigner` scheme results for
  every build so you can confirm the key is stable and v2-signed.
- **iOS (iPhone + iPad)**: `ColliderVis-iOS-unsigned` is an unsigned IPA
  built with xcodebuild — sideload it with AltStore/Sideloadly, or take
  the `ColliderVis-iOS-XcodeProject` artifact, open it in Xcode, set your
  own team/signing, and deploy directly. Phones/tablets run at the
  0.5 render-scale floor with the Performance preset and no lens pass
  for smoothness, with a full touch interface: one finger orbits, pinch
  zooms, ☰ opens the menu, a bottom action bar gives Prev/Next event,
  camera mode, and cutaway, and walk mode gets a virtual joystick +
  jump button with drag-look on the right half of the screen.

## Status of the UE5 project

`ColliderVis/` (the UE5 C++ project) is kept for reference, but building it
requires Epic's credential-gated engine (Epic account + GitHub org join +
`ghcr.io` login — see `Dockerfile.ue5build`), which cannot run in CI or
headless containers without those credentials. The Godot port replicates its
design: the same hall/light-rig concept from
`ColliderVisGameMode::SetupAtmosphere`, the same track/calo-hit/MC color
conventions, and the same event JSON schema.
