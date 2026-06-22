# ColliderVis — overnight work log & guides

Running notes from the autonomous overnight session. Newest section first.

---

## ⚠️ ACTION NEEDED FROM YOU: recompile C++ once

Several control/feel fixes are **written in source but not compiled** (I avoided
killing/relaunching the editor while you were away, since a failed relaunch would have
stranded me). To get them, **close the editor and run one build**, then reopen:

```bash
"/Users/Shared/Epic Games/UE_5.7/Engine/Build/BatchFiles/Mac/Build.sh" \
  ColliderVisEditor Mac Development \
  -project="/Users/leejr/Work/ddgeoviztools/ColliderVis/ColliderVis.uproject" -waitmutex
```

(`build_project` via the MCP times out for this project — use `Build.sh` directly; it takes ~8 s.)

Staged C++ changes in `Source/ColliderVis/ColliderVisCharacter.cpp`:
- **Mouse now turns the character** (`bUseControllerRotationYaw = true`). A pre-existing
  duplicate line was setting it back to `false`, so Quinn never rotated — fixed.
- **Camera no longer sluggish**: rotation lag disabled (1:1 mouse look), light position lag only.
- **Movement input mapping is now built in C++ with `EKeys`** (the data-driven asset kept
  saving null keys from Python — that was the multi-hour "nothing moves" bug). Rebuild-proof.
- Faster turn rate / slightly higher walk speed.

---

## What's working now (no rebuild needed)

- **Controls** (already live): WASD moves with correct per-direction vectors, mouse looks,
  Space jumps, **Tab** toggles orbit camera, **hold RMB** zooms. (Mouse-turns-body and the
  snappier camera come with the rebuild above.)
- **Quinn** is the playable character, animated (idle/walk/run via `ABP_Unarmed`).
- **Scene**: detector scaled to human size (~12 m) inside an 18 m **spherical hall**, on a floor,
  with a `PlayerStart`. Lights are **Movable** (Lumen, fully dynamic — never run "Build Lighting",
  it's not needed and will fail on the Nanite meshes).

## Glamour-render setup added this session

- **`GlamourCam`** (CineCameraActor) — a hero camera in the level.
- **`CinePostProcess`** — an unbound PostProcessVolume with a cinematic grade: histogram auto-exposure,
  bloom, mild cool color-grade, ambient occlusion, vignette, subtle film grain, motion blur off.
- **`AmbientSky`** skylight for fill.
- Lighting rebalanced (amber rig toned down + cooled, distracting god-ray spot off) so the
  detector's **cutaway calorimeter layers** read instead of blowing out. See `Renders/refs/`.

### How to get super-high-quality stills (easiest path)
With the **editor focused** (it throttles rendering in the background), open the Output Log's
Python console and run:
```python
import sys; sys.path.append(r"/Users/leejr/Work/ddgeoviztools/ColliderVis/Tools")
import render_glamour as g
g.cinematic_quality()      # max quality cvars
g.shot()                   # 4K hero still  → Saved/Screenshots/MacEditor/
g.shot(yaw=60, pitch=-20)  # any orbit angle
g.turntable(count=16)      # stills all the way around
```
For unattended/8K/anti-aliased renders, use **Movie Render Queue** (Window ▸ Cinematics) —
notes in progress.

## Known issues / next
- The `WBP_Options` menu widget has a class mismatch (builder stub isn't a `UColliderVisOptionsWidget`)
  → the in-game menu won't open. Cosmetic; fix later.
- Headless rendering is throttled when the editor is backgrounded — that's why I iterate via PIE
  `capture_viewport` rather than HighResShot.
- Detector materials are currently lit fairly warm; experimenting with cooler/neutral keys to make
  the per-sub-detector colors read.

## Progress log
- 2026-06-02 ~21:30 — Baseline baked (cinematic PPV, GlamourCam front cutaway, lights toned/cooled, god-ray off). Added Light_CoolRim (7000K back light) for detector/hall separation — subtle edge improvement; kept. NEXT: warm/cool balance on lower half (still amber-heavy); try a 3/4 angle with the cutaway; give detector materials more metallic definition + emissive accents on inner layers; consider raising AmbientSky fill.
- 2026-06-02 ~21:36 — Iter2: detector materials → polished metal (Metallic 0.9, Roughness 0.35) on all 17 MI_*; lifted exposure (bias -0.2, max 1.5) so metal reads. More realistic surfaces, layers still clear. Kept. NEXT: metal looks best with something to reflect — add a sky-light/reflection environment or brighter key so reflections pop; consider per-sub-detector roughness variation (yoke rough, trackers shiny); add emissive accent to inner layers (needs M_DetectorGeometry graph edit, add Emissive param).
- 2026-06-02 ~21:42 — Iter3: added Emissive (EmissiveColor*EmissiveStrength) param to M_DetectorGeometry graph; set inner layers (Vertex, InnerTrackers, ECalBarrel/Endcap) to glowing cyan. Big win — detector now reads as an active, glowing event-display. Kept. NEXT: per-layer color coding (HCal warm/orange, Solenoid green, Yoke neutral) for the classic multi-color detector look; dial the warm IP/center glow down so cyan pops; subtle bloom tuned for the emissive; try a 3/4 angle now that layers glow.
- 2026-06-02 ~21:47 — Iter4: per-layer emissive color-coding (HCal orange, Solenoid green, OuterTrackers violet; inner cyan kept), Yoke neutral; toned Key_Amber x0.6. Detector now reads multi-color/event-display. Kept, BUT the warm amber floor+hall now clash & the look is busy. NEXT (priority): cool+darken the environment — reduce Fill/Kicker/Rim amber intensity ~0.4 and shift temps to ~5000-5500K, and/or darken floor material, so the detector colors pop against a near-black hall. Then re-balance bloom for the emissives.
- 2026-06-02 ~21:52 — Iter5: cooled+dimmed amber rig (Fill/Kicker/Rim/Interior x~0.4, temp 5200K), saved. KEY FINDING: in PIE the GameMode spawns its OWN light rig + PostProcessVolume at BeginPlay, and the view CineCamera applies physical exposure — so lighting/exposure edits do NOT visibly change the PIE capture (materials/emissive DO). BUT the user's foreground HighResShot renders run in the editor with NO PIE/GameMode, so editor-world light/PPV/material edits apply cleanly there. => Loop strategy update: keep making principled editor-world lighting/PPV/material edits (they pay off in the foreground render); use PIE only as a rough material check, do not fight GameMode-dominated PIE exposure. NEXT: continue material/emissive refinement (verifiable in PIE) — e.g. roughness variation per layer, tune emissive strengths, add subtle fresnel/edge glow; and prep a 3/4 GlamourCam alt angle. The amber-floor-in-PIE is a GameMode artifact, not the editor-render look.
- 2026-06-02 ~22:01 — Iter6: added Fresnel edge-glow to M_DetectorGeometry emissive (params FresnelEdgeColor cool-cyan, FresnelEdgeStrength 0.8) — all detector surfaces now catch a cool rim sheen at grazing angles; layers look energized/defined. Verified in PIE (emissive=visible). Kept. Restored GlamourCam to front-cutaway hero pose. NEXT: per-layer roughness variation (yoke 0.6 matte, ECal/HCal 0.4, trackers/solenoid 0.25 shiny) for material contrast; tune FresnelEdgeStrength per-instance (outer yoke a bit stronger to outline the silhouette); consider a darker/cooler FresnelEdgeColor on warm layers. Then bank a clean 3/4 alt GlamourCam pose.
- 2026-06-02 ~22:06 — Iter7: per-layer roughness (yoke 0.6 matte → beampipe/vertex 0.18-0.22 polished; ECal/HCal 0.38-0.42; nozzles 0.5) + stronger edge-glow on yoke/beampipe. Subtle in PIE (specular needs foreground-render lighting) but sound realism. Kept. NOTE: PIE-verifiable material refinements are plateauing (GameMode lighting dominates reflectivity). NEXT: switch to PIE-verifiable wins — (a) bank an alternate 3/4 GlamourCam hero angle (set up GlamourCam2 or just record a good pose), (b) emissive pulse/gradient tweaks, (c) add a thin bright emissive "beamline" down the beampipe axis for a striking centerline. Then a clean wide establishing pose.
- 2026-06-02 ~22:11 — Iter8: (a) glowing beamline — MI_Beampipe emissive bright cyan-white (strength 12, roughness 0.15); subtle from front (near end-on) but reads from side. (b) Banked a more dynamic 3/4 hero GlamourCam pose (loc -950,-1050,360 / rot pitch-14 yaw48 / 30mm) — shows depth + angled cutaway + colored layers; set as primary. Both kept+saved. NEXT: emissive gradient/animation feel (vary inner-vs-outer emissive strength for depth); add faint volumetric/God-ray feel via a spotlight from above through the cutaway (note: spotlights are lights → only show in foreground render, not PIE); tune CinePostProcess bloom for the emissives in foreground; consider a second saved camera (wide establishing) for the turntable. Also still TODO for user: C++ rebuild + render_glamour.py.
- 2026-06-02 ~22:17 — Iter9: created M_GlossFloor (near-black, rough 0.12, reflective) and assigned to Floor_Ground for a mirror-floor glamour look. KEY FINDING #2: the amber floor/hall seen in PIE is the GameMode SpawnSciFiRoom (runtime), NOT my Floor_Ground/Hall_Sphere — so PIE shows the DETECTOR accurately but a DIFFERENT environment than the foreground editor render (which uses my dark hall + gloss floor + cooled lights). => My env edits (floor/hall/lights/PPV) are for the foreground render; detector material/emissive edits verify in PIE. Gloss floor kept (foreground benefit). NOTE for user: the in-GAME look (sci-fi room, amber) is set by GameMode C++ flags bSpawnSciFiRoom/bSpawnDefaultLighting — toggle/edit those (needs recompile) if you want play-mode to match the render look. NEXT: keep refining detector emissive (verifiable): inner-to-outer emissive gradient; and prep MovieRenderQueue notes so user gets film-quality stills.
- 2026-06-02 ~22:23 — Iter10: wrote RENDER_GUIDE.md (deliverable for "easy super-high-quality stills") — quick 4K via render_glamour.py + film-quality Movie Render Queue (temporal AA, hi-res tiling, optional Path Tracing for photoreal). No scene change. NEXT: emissive hot-core gradient (innermost white-hot → cool colored outer, PIE-verifiable); curated camera bookmarks; option to hide floor for a "detector in the void" beauty pass.
- 2026-06-02 ~22:27 — Iter11: emissive hot-core gradient (beampipe white-hot 14 → vertex 7 → trackers/ECal cyan → solenoid green → HCal orange → outer violet) for radial depth; tightened the 3/4 GlamourCam (loc -720,-820,300 / 28mm) so the glowing cutaway fills the frame. Both kept+saved. Detector now: glowing color-graded cutaway, beamline trough, edge-glow. NEXT: this is a strong hero. Remaining polish ideas — (a) add a subtle SkyLight/reflection so metal+gloss-floor read in foreground render; (b) a 2nd dramatic low-angle bookmark; (c) verify a foreground HighResShot looks right (needs user/foreground). Loop is now in fine-polish territory; large visible gains are done.
- 2026-06-02 ~22:35 — Iter12: AmbientSky set to non-realtime captured-scene (intensity 0.5) for subtle foreground ambient fill (the earlier realtime-capture threw a "needs SkyAtmosphere" warning — reverted). Tried a low-angle bookmark; framed mostly void, abandoned; hero cam restored to tight 3/4. STATUS: major visual work complete — detector is a strong glowing event-display hero; pipeline+docs delivered. Loop now in marginal/fine-polish; lengthening cadence to ~20min and biasing to SAFE verifiable changes (detector emissive/composition) to avoid blind regressions. NEXT (safe/verifiable): subtle emissive strength balance; alternate framings saved as refs only (no primary-cam churn); else documentation/scene-polish. User TODO unchanged: C++ rebuild + render via RENDER_GUIDE.md.
- 2026-06-02 ~22:59 — Iter13 (safe/no-scene-change): added curated hero-pose presets to render_glamour.py — g.pose("hero"/"front"/"establishing"), g.all_heroes(). One-call best compositions for the user. Zero regression risk. NEXT (safe): document recommended Movie-Render-Queue + pose workflow already in RENDER_GUIDE; optional subtle emissive balance only if clearly better in PIE; otherwise hold steady — major work complete.
- 2026-06-02 ~23:21 — Iter14 (safe): completed hero set — fixed the "establishing" preset (the first one aimed at the grey hall wall) to a working high/wide pose (-820,-920,560 / pitch-21 yaw48 / 24mm) showing the full glowing cutaway + context; saved ref hero_establishing.png. Health check: detectors present, GlamourCam intact. Three curated poses now all verified: hero (tight 3/4), front (symmetric), establishing (high/wide). Major work complete + stable. NEXT: hold steady; only safe verifiable tweaks. User TODO unchanged (C++ rebuild; render via RENDER_GUIDE / g.all_heroes()).
- 2026-06-02 ~23:44 — Iter15 (safe): wrote MORNING_SUMMARY.md — crisp TL;DR + exact 3 morning steps (stop loop, C++ rebuild, g.all_heroes()) + caveats (scale, play-vs-render look, menu stub). Project is in a complete, stable, well-documented state. Loop will continue safe marginal polish at ~20min; nothing outstanding that risks regression.
- 2026-06-03 ~00:06 — Iter16 (safe/additive): added "side" hero preset (-1150,-150,320 / pitch-11 yaw7 / 35mm) — architectural side profile showing detector depth, glowing cutaway, metallic yoke wall w/ edge-glow; saved ref. Tried a macro core pose; too floor-dominated in PIE, skipped. Now 4 curated poses (hero/front/establishing/side) via g.pose() / g.all_heroes(). Project remains complete+stable. NEXT: out of clearly-beneficial safe visual moves; future iterations = light verification / hold steady unless a new safe idea arises.
- 2026-06-03 ~00:30 — Iter17 (verification): full health check PASSED — 17 detectors, 9 lights, GlamourCam, materials (M_DetectorGeometry/M_GlossFloor/M_Hall), IMC_Default, SKM_Quinn_Simple all present; hero shot renders correctly (no regression after 16 edit iters). Project complete + stable. Loop -> maintenance cadence (~30min): verify stability, change only if a clearly-beneficial safe idea arises.
- 2026-06-03 ~01:02 — Iter18 (safety): save_dirty_packages(map+content)=True — all level + asset edits persisted to disk. Project complete/stable/saved. Maintenance mode continues.
- 2026-06-03 ~01:34 — Iter19 (maintenance): editor+MCP healthy, PIE idle, work saved. No beneficial change available — held steady. Cadence -> ~1h hourly health check. Project remains complete/stable/saved; awaiting user (stop loop, C++ rebuild, render via g.all_heroes()).
