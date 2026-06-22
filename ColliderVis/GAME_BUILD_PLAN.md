# ColliderVis → AAA Game Build Plan

Master spec for the autonomous build. All agents read this. Owner of integration,
compilation, and the live UE editor is the **orchestrator** (main Claude session).

## Vision
A photorealistic, cinematic, interactive event display for the **MAIA Detector Concept**
(US Muon Collider). Splash screen on launch, walkable third-person hero character inside a
huge display hall, Esc menu to toggle detector sub-systems, over-the-shoulder aim zoom,
EDM4hep event loading with particles that animate outward from the collision point along
their trajectories by propagation time, and Hollywood-grade moody lighting + post.

## Hard constraints
1. **Platform: Apple Silicon / macOS / Metal.** UE5 hardware Path Tracer is effectively
   unavailable. "Ray-traced / non-realtime renders" = **Lumen (high/HWRT-quality) via Movie
   Render Queue**. Keep the scene path-tracer-friendly for a future Windows/RTX pass.
2. **C++ changes require a recompile**, which means closing the editor (the MCP server runs
   inside it). All editor/MCP work batches between rebuilds. Build command:
   ```
   "/Users/Shared/Epic Games/UE_5.7/Engine/Build/BatchFiles/Mac/Build.sh" \
     ColliderVisEditor Mac Development \
     -project="/Users/leejr/Work/ddgeoviztools/ColliderVis/ColliderVis.uproject" -waitmutex
   ```
3. **One editor driver.** Agents do NOT touch the running editor or MCP. They only edit
   source files in `Source/ColliderVis/` (and Tools/ for the pipeline). The running editor
   uses compiled binaries, so source edits are safe until the orchestrator recompiles.
4. **Disjoint file ownership** (below) — no two agents edit the same file.

## Existing scaffolding (from audit — build on it, do not duplicate)
- `AColliderVisGameMode` — spawns post-process/fog always; `SetupDefaultLightRig()` gated by
  `bSpawnDefaultLighting`(default false); `SpawnSciFiRoom()` gated by `bSpawnSciFiRoom`(false).
  DefaultPawn=`AColliderVisCharacter`, HUD=`AColliderVisHUD`.
- `AColliderVisHUD` — ShowMenu/HideMenu/ToggleMenu, auto-discovers `/Game/UI/WBP_Options`.
- `UColliderVisOptionsWidget` — full C++ API: `GetSubDetectorList()`, `SetSubDetectorVisible()`,
  `SetAllSubDetectorsVisible()`, `RequestNextEvent()/RequestPreviousEvent()`, `BrowseAndLoadFile()`,
  `RequestClose()`; BIE events OnMenuShown/OnEventStateChanged/etc.
- `ADetectorVisibilityManager` — tag-based sub-detector grouping; `SetSubDetectorVisible(Name,b)`,
  `SetAllVisible(b)`, `ToggleSubDetector(Name)`, `RebuildActorCache()`.
- `AColliderVisCharacter` — SpringArm `CameraBoom`(400cm, lag 20) + `FollowCamera`(FOV 90);
  IA_Zoom on RMB already lerps boom 400→150 & FOV 90→40; orbit mode on Tab. Input mapping is
  **code-generated in SetupPlayerInputComponent** (EKeys), asset IMC is fallback only.
- `AEventDisplayManager` — parses EDM4HEP ROOT→JSON via `Tools/edm4hep_to_json.py`, spawns
  track/calo/MC actors per event; `BP_EventDisplayManager` instance in level.
- Scene `ColliderVisMain`: `Hall_Sphere` (display dome, no collision, scale -100), detector
  static meshes at origin, PlayerStart at (0,0,110), 11 lights, PostProcessVolume_0 (tuned).

## Cinematic look spec (already applied live to PostProcessVolume_0 — AGENT-RENDER must
## replicate these in C++ `SetupPostProcessAndFog` so PIE matches the editor look)
- AutoExposure Histogram, min 0.03 / max 2.0 / bias 0.6, ApplyPhysicalCameraExposure off.
- White balance temp 5800. ColorSaturation 1.06, ColorContrast 1.08.
  Warm highlights gain (1.06,1.0,0.90); cool teal shadows gain (0.94,1.0,1.08) — warm-leaning
  teal/orange. LocalExposure highlight contrast 0.85.
- Bloom SOG intensity 0.8 threshold 1.0. SceneFringe (chromatic) 1.0, start offset 0.4.
- AO intensity 0.7 radius 200 power 2.5. Vignette 0.45. FilmGrain 0.12. MotionBlur 0.4.
- DoF f/2.8, focal 2200, sensor 36mm. LensFlare 0.3.
- Lumen reflections quality 2, final-gather quality 4. ReflectionMethod Lumen.
- Lights: warm (temp 4200–4500K), volumetric scattering 2–3 for god rays through the existing
  volumetric exponential height fog. Target: soft, warm, moody, Hollywood.

## Workstreams & file ownership
- **AGENT-CHAR** → `Source/ColliderVis/ColliderVisCharacter.{h,cpp}` ONLY.
  Over-shoulder RMB aim zoom (boom shortens + side socket offset + FOV) AND hide the character
  mesh (`GetMesh()->SetVisibility(false)` / SetOwnerNoSee) while zoomed, restore on release.
  Realistic camera: enable spring-arm rotation lag + position lag, smooth FOV, subtle aim
  offset. Bind LMB (left mouse) to call the event manager's `PlayNextEventAnimated()` (find via
  GetAllActorsOfClass<AEventDisplayManager>). Keep existing orbit/zoom behavior working.
- **AGENT-EVENT** → `EventDisplayManager.{h,cpp}`, `TrackActor`/`CaloHitActor`/`MCParticleActor`
  files, + NEW `ParticlePropagation` logic. Implement `PlayNextEventAnimated()`: advance to next
  event, then animate each particle emerging from the collision center (origin), revealing its
  trajectory progressively by **propagation time along the trajectory** (parametrize tracks by
  arc length / time-of-flight; reveal spline up to ct). Robust EDM4hep ingestion via existing
  `Tools/edm4hep_to_json.py`. Provide `LoadEDM4hepFile(path)`.
- **AGENT-RENDER** → `ColliderVisGameMode.{h,cpp}` rendering functions only
  (`SetupPostProcessAndFog`, `SetupDefaultLightRig`). Port the cinematic look spec above into
  C++ so PIE matches editor. Add a soft warm cinematic key/fill/rim rig with volumetric
  scattering (god rays). Default `bSpawnDefaultLighting=true` with the NEW warm rig. Add a
  Movie Render Queue preset doc/config for Lumen non-realtime renders.
- **AGENT-FLOW** → NEW files only: `ColliderVisGameInstance.{h,cpp}` + `SplashWidget.{h,cpp}`
  (UUserWidget C++ base exposing logo/credit text for the UMG asset). Boot flow: show splash
  with the USMCC logo (`Tools/_assets/USMCCLogo_color_white.png`, to be imported to
  `/Game/UI/Textures/T_USMCCLogo`), then enter `ColliderVisMain`. Skippable on click/any-key.
  Minimal GameMode edit is FORBIDDEN — use GameInstance/level-blueprint flow to avoid conflict
  with AGENT-RENDER.

## Orchestrator-owned (editor/MCP, not agents)
- Esc menu UMG: `WBP_Options` reparent/fix to `UColliderVisOptionsWidget`; add per-sub-detector
  toggles, credit "Lawrence Lee (UTK)" linking to https://muoncollider.us, label "MAIA Detector
  Concept", nice font. Splash UMG `WBP_Splash`. Logo + font import. Detector scale review.
  Materials/photoreal pass. Renders.
- Integration: review agent diffs, compile, fix errors, relaunch editor, verify via PIE+capture.

## Build/verify protocol
1. Agents finish → orchestrator reviews each diff for the owned files only.
2. Orchestrator does all pending live editor work, saves all assets.
3. Close editor → Build.sh → fix compile errors → relaunch editor (MCP reconnects).
4. Verify: StartPIE, CaptureViewport, confirm each feature; iterate.

## ART-DIRECTOR POLISH PUNCH-LIST (apply during Wave-2 material/lighting pass)
- Floor: too mirror-like/bright → roughness ~0.35–0.45, specular ~0.5, add roughness breakup
  so reflections smear (polished concrete, not showroom plastic).
- Detector: reads as a featureless white blob → pull emissive WAY down, add metallic ring/panel
  segmentation + roughness variation so barrel/endcap forms read; add a rim/back light to carve
  the silhouette.
- Lighting: build a true 3-point (warm key, ~4:1 key/fill, warm rim camera-left-rear, low cool
  fill camera-right); interior practical at ~20%.
- Remove the stray bright "star" light/flare sprite (upper area).
- Lift shadows slightly (global black ~+0.01) so dome/walls read at ~5–12% luminance, not crushed.
- Master grade warm-leaning (Temp ~5500–6000K); blue is accent only. Bloom 0.4–0.6, threshold 1.0.
- Hero renders: hide editor grid + axis gizmo; offset/3-4 framing for depth.

## PERFORMANCE (PIE felt sluggish — ongoing optimization mandate)
Perf levers (apply/verify; expose user toggles via the settings menu):
- DONE: GameMode `bSpawnDefaultLighting=false` (no rig doubling), `bSpawnCinematicCameras=false`
  (no 7 ticking camera actors in gameplay), in-level PPV LumenFinalGather 4→2 / reflections 2→1.
- TODO/verify: avoid double PPV+SkyLight spawn in PIE (guard `SetupPostProcessAndFog` to skip when
  an in-level PPV/SkyLight exists; still spawn fog). Volumetric fog is costly — provide quality
  toggle + sane default grid size. Reflective floor reflections are costly — roughen floor.
  Consider Nanite on detector meshes, disabling per-object motion blur, capping shadow cascades.
- Perf agent (task #10): after each compile, StartPIE → `stat fps`/`stat unit` → record ms on
  GPU/Game/Draw → flag regressions; MRQ-quality reserved for non-realtime renders only.

## WAVE 2 (after Wave-1 compile + verify)
- **Settings menu** (UMG + `UGameUserSettings` subclass `UColliderVisUserSettings` or use stock):
  mouse-sensitivity slider (drives the character look scale — add a runtime-settable
  `LookSensitivity` UPROPERTY on `AColliderVisCharacter`), master quality preset buttons
  (Low/Med/High/Epic/Cinematic → `Scalability` groups), and individual toggles for expensive
  features: Lumen reflections, volumetric fog/god rays, motion blur, bloom, DoF, film grain,
  screen-space shadows, Nanite. Persist to GameUserSettings ini. Accessible from the Esc menu.
- **Idle / bored animation**: track time-since-last-input on `AColliderVisCharacter`; after
  ~15s idle, trigger a "bored" idle state in the AnimBP (look around, shift weight, check watch).
  Needs C++ idle timer + AnimBP state/montage. Use available Quinn idles; author a simple
  bored montage/state if none exists.
- **Cutout positioning**: character should stand at the detector cutaway, at **y=0 in detector
  coords** (detector is at world origin, so PlayerStart at y=0). Verify in PIE the spawn sits at
  the open cutaway facing inward, on the floor; refine PlayerStart X/Z and yaw after seeing it.
- **Sphere (done live)**: scale brought −100 → −70 (more visible); soft warm interior fill light
  `FillLight_Interior` (PointLight, 4000K, soft, shadowless, VSI 1.5) added at center.
- **Integration note (Wave 1 lighting)**: keep in-level PPV_0 + tuned lights authoritative;
  set GameMode `bSpawnDefaultLighting=false` to avoid PIE light-doubling with the C++ rig.
  Consider making `SetupPostProcessAndFog` skip spawning when an in-level PPV exists.
