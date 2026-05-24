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

## Step 2 — Export from .blend to UE5-ready GLTF + manifest.json

Requires Blender 4.x installed on your machine.

```bash
blender --background /data/detector.blend \
        --python /home/user/ColliderVis/Tools/blend_to_ue5.py \
        -- --output-dir /tmp/ue5_meshes/
```

Output:
```
/tmp/ue5_meshes/
    ECalBarrel.gltf
    HCalBarrel.gltf
    Solenoid.gltf
    ...
    manifest.json
```

## Step 3 — Import GLTF files into UE5

1. Open UE5 project `ColliderVis.uproject` in the Unreal Editor.
2. Enable the **glTF Importer** plugin: *Edit → Plugins → search "glTF" → Enable → Restart*.
3. In the Content Browser, navigate to `Content/Detector/` (create folder if needed).
4. Drag-and-drop all `*.gltf` files from `/tmp/ue5_meshes/` into the Content Browser.
5. In the Import dialog:
   - **Generate Lightmap UV**: Yes
   - **Import Normals**: Yes
   - **Build Nanite**: Check (or enable per-asset afterwards)
   - **Collision**: None (decorative geometry)
6. Click **Import All**.

## Step 4 — Drag meshes into the level

1. Open `Content/Maps/ColliderVisLevel` (or create a new level).
2. For each imported static mesh (`SM_ECalBarrel`, etc.), drag it from the Content Browser
   into the viewport.
3. Place meshes at origin (0, 0, 0) — they are already in detector-centred coordinates.
4. Set each actor's **Mobility** to **Static** in the Details panel.

## Step 5 — Apply Actor Tags via Editor Python

1. *Edit → Execute Python Script* → select `Tools/ue5_tag_actors.py`
2. Or run from the output log console:
   ```python
   import subprocess
   subprocess.run(["python", "Tools/ue5_tag_actors.py",
                   "--manifest", "/tmp/ue5_meshes/manifest.json",
                   "--content-path", "/Game/Detector"])
   ```
   This sets actor tags and enables Nanite on each mesh asset.

## Step 6 — Populate DA_DetectorVisibility

1. Right-click in Content Browser → *Blueprint → Data Asset → UDetectorVisibilityConfig* →
   name it `DA_DetectorVisibility`.
2. For each entry in `manifest.json`, add a row:
   - **Name**: sub-detector name (e.g. `ECalBarrel`)
   - **bVisibleByDefault**: true
   - **LabelColor**: use the `base_color` from manifest (for the UI panel swatch)
   - **ActorTags**: `["ECalBarrel"]`
3. Assign `DA_DetectorVisibility` to the `ADetectorVisibilityManager` actor in the level.

## Step 7 — Blueprint Assets to Create (after C++ compile)

| Asset | Parent | Location |
|-------|--------|----------|
| `BP_ColliderVisCharacter` | AColliderVisCharacter | Content/Blueprints/ |
| `BP_EventDisplayManager`  | AEventDisplayManager  | Content/Blueprints/ |
| `BP_CineCamera`           | AColliderVisCineCameraActor | Content/Blueprints/ |
| `WBP_EventMenu`           | UEventMenuWidget      | Content/UI/ |
| `WBP_DetectorVisibility`  | UUserWidget           | Content/UI/ |
| `DA_EventDisplayConfig`   | UEventDisplayConfig   | Content/Data/ |
| `IMC_Default`             | UInputMappingContext  | Content/Input/ |
| `IA_Move`, `IA_Look`, `IA_Jump`, `IA_NextEvent`, `IA_OpenMenu`, `IA_SwitchMode`, `IA_ToggleDetectorMenu` | UInputAction | Content/Input/ |

## Verification Checklist

- [ ] All GLTF meshes imported, visible in Content Browser
- [ ] `stat Nanite` in PIE console shows virtual geometry active
- [ ] Actors in World Outliner show `Mobility = Static`
- [ ] Actor Tags set correctly (select actor → Details → Actor → Tags)
- [ ] `DA_DetectorVisibility` has entries matching manifest
- [ ] `ADetectorVisibilityManager` placed in level with Config assigned
- [ ] `BP_EventDisplayManager` placed with `DA_EventDisplayConfig` assigned
- [ ] Press D in PIE → `WBP_DetectorVisibility` toggles ECal/HCal/Tracker visibility
