# ColliderVis — Photoreal Walk-Around on Quest (Gaussian Splatting)

This is the **fully automated** alternative to the UE5 path. There are no
manual editor steps: you go from a `.blend` to a 6DoF photoreal scene you can
walk around in the Meta Quest browser with three commands and one drag-and-drop.

The trick that makes it reliable: the views are **rendered**, so the camera
poses are known exactly. There is no COLMAP / structure-from-motion step (the
slow, flaky part of photogrammetry) — `render-views` hands the trainer perfect
poses straight from Blender.

```
test.blend ──(1. render-views)──> posed Cycles images ──(2. Brush)──> splat.ply ──(3. WebXR)──> Quest
```

## What you keep, what you give up

- **Keep:** the Cycles *look* (lighting, materials, reflections), real 6DoF —
  walk around and through the detector — and a zero-install Quest viewer.
- **Give up:** it's a **static bake** of one lighting state / one event. Live
  event-swapping and detector toggles are not in this path (that's the UE5
  build). Re-rendering + re-training is the way to change the scene.

---

## 1. Render posed views (headless, automated)

Runs inside the existing Docker image, exactly like the other subcommands:

```bash
./run.sh render-views /data/test.blend \
    --output-dir /data/splat_views/ \
    --num-views 300 \
    --resolution 1280 \
    --samples 128 \
    --hide-volume
```

Output:

```
splat_views/
├── images/
│   ├── frame_00000.png   (RGBA, transparent background)
│   └── ...
└── transforms.json       (nerfstudio/NeRF poses — ready for Brush)
```

| Flag | Default | Notes |
|------|---------|-------|
| `--num-views` | 150 | Use **300–500** for HEP geometry — thin shells and fine structure need many angles to pin down. |
| `--resolution` | 1280 | Square px per view. Higher = sharper splat, slower render/train. |
| `--samples` | 128 | Cycles samples per view. The images only need to be *clean*, not 4K-final. |
| `--fov` | 50 | Horizontal camera FOV (degrees). |
| `--margin` | 1.15 | Framing slack around the detector's bounding sphere. |
| `--hemisphere` | off | Only orbit the upper half (+Y). Default is a **full sphere** for complete coverage. |
| `--hide-volume` | off | **Recommended on.** Strips the world Volume Scatter (atmospheric fog) — volumetrics reconstruct badly as Gaussians. |
| `--interior-views` | 0 | **Use this to see into the centre.** Adds N extra cameras *inside* the phi-cutaway opening, aimed radially inward at the core. Try **80–150**. |
| `--interior-radius` | 0.55 | Interior camera distance from the beam axis, as a fraction of the detector bounding radius. Smaller = deeper inside. |
| `--cut-phi-min` / `--cut-phi-max` | auto | Edges of the removed cutaway sector (degrees). Auto-read from the scene's `PhiCutawayControl`; override if the bake used a different sector. |

### Seeing into the centre (cutaway interior)

The exterior orbit looks at the detector from outside. To capture the **inner
detectors revealed by the phi-cutaway** so you can stand inside and look out,
add interior views:

```bash
./run.sh render-views /data/test.blend \
    --output-dir /data/splat_views/ \
    --num-views 300 \
    --interior-views 120 \
    --hide-volume
```

These cameras sit *inside the open wedge* (the removed sector) and look
radially inward at each beam cross-section, so their sightlines pass through
the opening to the core. The opening direction is taken from the scene's
`PhiCutawayControl` automatically; if your bake used a different sector, pass
`--cut-phi-min` / `--cut-phi-max`. Move the cameras deeper toward the beampipe
with a smaller `--interior-radius` (e.g. `0.35`).

> The cutaway in `test.blend` is **baked into the meshes**, so the opening is
> fixed at render time. To open a *different* sector, rebuild the `.blend` with
> `blender-scene --phi-cut/--phi-min` first, then render.

> **Speed:** in Docker this is CPU Cycles. For a real run, do it on your Mac
> with a normal Blender install — it'll use the Metal GPU and is much faster:
> ```bash
> blender --background test.blend --python src/render_views.py -- \
>     '{"output_dir":"./splat_views","num_views":300,"resolution":1280,"samples":128,"fov_deg":50.0,"margin":1.15,"hemisphere":false,"hide_volume":true}'
> ```

---

## 2. Train the splat with Brush (Mac, no CUDA)

[Brush](https://github.com/ArthurBrussee/brush) is a cross-platform 3DGS
trainer/viewer (Rust + wgpu). It trains on Apple Silicon via Metal — no NVIDIA
GPU required — and reads the `transforms.json` format we emit directly.

1. Grab a Brush release binary for macOS (or `cargo install` from source).
2. Point it at the render output:

   ```bash
   brush ./splat_views/
   ```

3. Let it train (a few minutes to ~half an hour depending on view count and
   how long you let it refine). Export the result as a `.ply` Gaussian splat.

That `.ply` is your photoreal detector.

---

## 3. View in the Quest browser (WebXR, zero install)

A self-contained viewer lives in `viewer/index.html` (three.js +
[GaussianSplats3D](https://github.com/mkkellogg/GaussianSplats3D), loaded from a
CDN — nothing to build).

1. **(Recommended) Convert `.ply` → `.ksplat`** for fast loading on Quest,
   using the GaussianSplats3D packaging tool (see its README). Name it
   `detector.ksplat`. A raw `.ply` or `.splat` also loads — just larger/slower.
2. Put the splat next to `viewer/index.html` (or pass `?src=URL`).
3. **Serve over HTTPS** — WebXR only enters VR from a secure context:
   - Easiest: commit `viewer/` + the splat to a **GitHub Pages** site and open
     the Pages URL. (Mind GitHub's 100 MB/file limit — `.ksplat` helps.)
   - Or any static HTTPS host / tunnel.
4. On the Quest, open the URL in the **browser**, then tap **Enter VR**. Walk
   around the detector in 6DoF.

The viewer assumes scene up is **+Y** (matching the render orbit). Override the
splat URL with `?src=`, e.g. `index.html?src=https://…/detector.ksplat`.

---

## Tuning notes for HEP geometry

- **Thin metal & wires** are the hard case for 3DGS. More views (400+) and a
  higher resolution help most. If a structure looks mushy, it was under-sampled.
- **Transparent/volumetric** elements (the world fog, any glass) won't splat
  well — `--hide-volume` removes the fog; consider hiding glassy volumes in the
  `.blend` before rendering if they ghost.
- **Interior coverage:** the default orbit views the detector from *outside*.
  If you want to stand *inside* and look out, render from a cutaway `.blend`
  (e.g. the phi-cut scene) so the interior is actually visible to the cameras.
- **Re-baking:** changing lighting, materials, the event, or the cutaway means
  re-running steps 1–2. Step 1 is one command; keep your favourite flag set in
  a shell script.
