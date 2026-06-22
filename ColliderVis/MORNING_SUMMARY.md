# ☀️ Morning summary — ColliderVis overnight session

Crisp TL;DR. Detailed log is in `NIGHTLY_NOTES.md`; rendering how-to in `RENDER_GUIDE.md`.

## Do these 3 things first
1. **Stop the loop** — it's still running (~20 min cadence). Just say "stop the loop" (or interrupt).
2. **Rebuild C++ once** (lands the movement/feel fixes — close the editor first):
   ```bash
   "/Users/Shared/Epic Games/UE_5.7/Engine/Build/BatchFiles/Mac/Build.sh" \
     ColliderVisEditor Mac Development \
     -project="/Users/leejr/Work/ddgeoviztools/ColliderVis/ColliderVis.uproject" -waitmutex
   ```
   Then reopen. (Use `Build.sh` directly for this project.)
3. **Render your glamour stills** — in the editor (foreground), Output Log ▸ Python:
   ```python
   import sys; sys.path.append(r"/Users/leejr/Work/ddgeoviztools/ColliderVis/Tools")
   import render_glamour as g
   g.cinematic_quality(); g.all_heroes()      # 4K hero/front/establishing → Saved/Screenshots/MacEditor/
   ```
   For film/path-traced quality, use Movie Render Queue (see `RENDER_GUIDE.md`).

## What got built tonight
- **Input/controls (staged in C++, needs the rebuild above):** WASD moves Quinn, mouse turns him,
  snappy camera, Space/Tab/RMB. Root cause of the long "nothing moves" fight: Python-authored
  input keys saved as null → rebuilt the mapping in C++ with `EKeys` (rebuild-proof).
- **Quinn** is the playable character, animated (idle/walk/run).
- **Detector glamour look** (huge upgrade): polished-metal materials, per-layer color coding,
  emissive hot-core gradient, Fresnel edge-glow, glowing beamline; in a dark hall with a glossy
  reflection floor, cooled cinematic lights, ambient fill, and a cinematic PostProcess grade.
- **Render kit:** `Tools/render_glamour.py` (`g.pose("hero"/"front"/"establishing")`, `g.all_heroes()`,
  `g.turntable()`), `RENDER_GUIDE.md`, and a progression of reference frames in `Renders/refs/`.

## Things to know / decide
- **Detector scale was ~1000× too big** (12 km); I scaled it to human size (~12 m). If your
  source data is meant to be a specific size, double-check the import scale in
  `Tools/blend_to_ue5.py` / `ue5_build_content.py`.
- **Play-mode vs render look differ:** when you *play*, the GameMode spawns its own amber "sci-fi
  room" + lighting (C++ flags `bSpawnSciFiRoom` / `bSpawnDefaultLighting` in `ColliderVisGameMode`).
  The *render* look (dark hall, glowing detector) is what `render_glamour.py` captures. Toggle those
  flags (needs a rebuild) if you want play-mode to match the renders.
- **`WBP_Options` menu** is a builder stub with a class mismatch — the in-game menu won't open yet.
- The `Renders/refs/*.png` are PIE captures (show the GameMode sci-fi room env); your foreground
  renders will look better (dark hall + gloss floor + bloom).

## Fixed earlier in the session (already live)
- The `.gltf`/`.glb` export-vs-manifest bug (no geometry was importing); lights set Movable
  (Lumen — no lighting build needed).
