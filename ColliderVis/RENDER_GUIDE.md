# ColliderVis — getting gorgeous high-quality stills

Two paths: **(A) quick 4K stills** in seconds, **(B) film-quality** via Movie Render Queue.
Both render the editor scene (dark hall, glossy floor, cooled cinematic lights, glowing
color-coded detector) — NOT the in-game sci-fi room (that's the GameMode at play-time).

> ⚠️ The editor must be the **foreground app** while rendering — UE throttles rendering when
> it's in the background, so a backgrounded editor produces black/stale frames.

---

## A) Quick 4K stills — `render_glamour.py` (recommended first)

In the editor: **Window ▸ Output Log**, set the bottom-left dropdown to **Python**, then:

```python
import sys; sys.path.append(r"/Users/leejr/Work/ddgeoviztools/ColliderVis/Tools")
import render_glamour as g
g.cinematic_quality()          # push scalability + Lumen to max
g.shot()                       # 4K hero still → Saved/Screenshots/MacEditor/
g.shot(yaw=48, pitch=-14, distance=1450)   # the banked 3/4 hero angle, framed wider
g.shot(yaw=90, pitch=-13)      # straight-on cutaway
g.turntable(16)                # 16 stills orbiting the detector (contact sheet)
g.shot(res="7680x4320")        # 8K
```
Output: `ColliderVis/Saved/Screenshots/MacEditor/HighresScreenshot*.png`.

The hero `GlamourCam` actor is in the level at the 3/4 pose — select it and click
**"Pilot" (the eyeball)** to look through it, or use the angles above.

---

## B) Film-quality — Movie Render Queue (MRQ)

For the absolute best stills (proper temporal AA, high sample counts, optional path tracing):

1. **Make a 1-frame Level Sequence bound to GlamourCam** (or just use the current viewport).
   - Cinematics ▸ Add Level Sequence → name it `SEQ_Hero`.
   - In Sequencer: **+ Track ▸ Camera Cut Track**, then **+ Camera ▸ GlamourCam**. Set the
     range to a single frame (0–1).
2. **Window ▸ Cinematics ▸ Movie Render Queue** → **+ Render** → pick `SEQ_Hero`.
3. Click the **Settings (Config)** entry and add:
   - **Anti-aliasing**: Temporal Sample Count **8–32**, Spatial **1**, Warm-Up frames ~32
     (lets Lumen + auto-exposure settle). Override Anti-Aliasing: **On**.
   - **High Resolution** (optional 8K+): tile count 2×2 or 3×3, overlap 64.
   - **Console Variables** (quality): `r.Lumen.Reflections.Quality=3`,
     `r.Lumen.ScreenProbeGather.RadianceCache=1`, `r.MotionBlurQuality=0`.
   - **Output**: format **PNG** (or **EXR** for grading latitude), 3840×2160 or higher,
     output dir e.g. `{project_dir}/Renders/`.
4. (Optional, photoreal) **Project Settings ▸ Rendering ▸ enable Path Tracing**
   (needs HW ray tracing). Then add the **Path Tracer** setting in MRQ, samples 256–1024.
   Path tracing gives true GI/reflections/soft shadows — the most "real" look.
5. **Render (Local)**. The editor renders offscreen (more reliable than HighResShot for long jobs).

---

## Tips for the best-looking frame
- Run `g.cinematic_quality()` first (or set Scalability ▸ Cinematic in the toolbar).
- The glowing detector + bloom looks best slightly underexposed — if too bright, lower
  Exposure Compensation in a PostProcessVolume or the camera.
- Reflections of the glowing detector in the **glossy floor** are a highlight — frame a bit
  lower / include the floor.
- For a "beauty" pass, hide the floor entirely (detector floating in the black hall) — select
  `Floor_Ground`, press **H**.
- Reference frames from the overnight iteration are in `Renders/refs/` (progression of the look).
