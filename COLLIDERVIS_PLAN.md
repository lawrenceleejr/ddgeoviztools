# Plan: ColliderVis — UE5 Photo-Realistic HEP Collision Event Visualizer

## Context

Build a new UE5 project at `/home/user/ColliderVis/` that:
1. Renders a detector geometry scene with photo-realistic Lumen/Path Tracer lighting
2. Supports two modes: **Movie/Still** (cinematic camera, no character) and **Explore** (playable third-person)
3. Loads EDM4HEP collision event files at runtime, displaying tracks, calorimeter hits, and MC particles
4. Allows advancing events with a mouse click and loading new EDM4HEP files via an in-game menu

Follows the [Unreal Engine Skill](https://github.com/DSTN2000/claude-unreal-engine-skill) **zero-assumptions protocol**:
- Discover all assets (IA_, IMC_, BP_) by path before referencing in code
- Use Enhanced Input System (no legacy input)
- Verify engine version from `.uproject` before using APIs
- Engine version: **UE5.7** (target; tested against 5.7.4)

---

## Project Structure

```
/home/user/ColliderVis/
├── ColliderVis.uproject
├── Config/
│   ├── DefaultEngine.ini        # Lumen, Path Tracer, TSR, VFog, VShadows
│   ├── DefaultGame.ini          # Default game mode → Explore
│   └── DefaultInput.ini         # No legacy bindings (Enhanced Input only)
├── Source/
│   └── ColliderVis/
│       ├── ColliderVis.Build.cs
│       ├── ColliderVis.h
│       ├── EDM4HEPTypes.h               # FEDMTrack, FEDMCaloHit, FEDMMCParticle, FEDMEvent
│       ├── EDM4HEPReader.h/.cpp         # JSON → FEDMEvent (FJsonSerializer)
│       ├── EventDisplayConfig.h/.cpp    # UDataAsset: collection toggles, colors, scale
│       ├── EventDisplayManager.h/.cpp   # AActor: orchestrates convert + spawn
│       ├── TrackActor.h/.cpp            # USplineComponent + USplineMeshComponents
│       ├── CaloHitActor.h/.cpp          # UInstancedStaticMeshComponent per collection
│       ├── MCParticleActor.h/.cpp       # UProceduralMeshComponent lines
│       ├── ColliderVisCharacter.h/.cpp  # ACharacter + Enhanced Input + spring arm
│       ├── ColliderVisCineCameraActor.h/.cpp  # ACineCameraActor wrapper
│       ├── ColliderVisGameMode.h/.cpp        # Explore mode
│       ├── ColliderVisVizGameMode.h/.cpp     # Movie/still mode (spectator)
│       ├── EventMenuWidget.h/.cpp            # UUserWidget C++ base for WBP_EventMenu
│       ├── DetectorVisibilityConfig.h/.cpp   # UDataAsset with FSubDetectorEntry array
│       └── DetectorVisibilityManager.h/.cpp  # AActor: tag-based actor grouping + visibility API
└── Tools/
    ├── edm4hep_to_json.py       # Python: EDM4HEP ROOT → per-event JSON
    └── requirements.txt         # uproot, awkward, numpy
```

---

## EDM4HEP→JSON Converter (`Tools/edm4hep_to_json.py`)

Called at runtime via `FPlatformProcess::CreateProc()`.

**CLI:** `python edm4hep_to_json.py <input.root> <output_dir/> [--event N]`

**Output:** `output_dir/event_NNNN.json` per event (or all events pre-converted on file load)

**JSON schema:**
```json
{
  "event_number": 42,
  "run_number": 1,
  "tracks": [
    { "points": [[x,y,z],...], "charge": 1.0, "momentum_gev": 15.3, "pdg": 211 }
  ],
  "calo_hits": [
    { "collection": "ECalBarrelHits", "position": [x,y,z], "energy_gev": 0.023 }
  ],
  "mc_particles": [
    { "vertex": [x,y,z], "end_vertex": [x,y,z], "momentum_gev": [px,py,pz],
      "pdg": 11, "charge": -1.0, "status": 1 }
  ]
}
```

All positions in **mm** (UE5 converts to cm via WorldScale = 0.1).

**Libraries:** `uproot` (ROOT TTree reading), `awkward` (array ops), `numpy`

---

## C++ Class Details

### `EDM4HEPTypes.h` — Data Structs
```cpp
USTRUCT(BlueprintType) struct FEDMTrack {
    TArray<FVector> Points; float Charge; float MomentumGeV; int32 PDG;
};
USTRUCT(BlueprintType) struct FEDMCaloHit {
    FVector Position; float EnergyGeV; FString CollectionName;
};
USTRUCT(BlueprintType) struct FEDMMCParticle {
    FVector Vertex; FVector EndVertex; FVector MomentumGeV; int32 PDG; float Charge;
};
USTRUCT(BlueprintType) struct FEDMEvent {
    int32 EventNumber; int32 RunNumber;
    TArray<FEDMTrack> Tracks;
    TArray<FEDMCaloHit> CaloHits;
    TArray<FEDMMCParticle> MCParticles;
};
```

### `UEventDisplayConfig` (UDataAsset)
Key `UPROPERTY(EditAnywhere)` fields:
- `TArray<FName> EnabledCaloCollections` — e.g. `{"ECalBarrelHits","HCalBarrelHits"}`
- `bool bShowTracks`, `bool bShowMCParticles`
- `float TrackTubeRadius` (default 2.0, UE cm)
- `FLinearColor PositiveTrackColor`, `NegativeTrackColor`
- `float CaloHitBaseSize` (5.0 cm)
- `float EnergyEmissiveScale` (multiplier for glow intensity)
- `float WorldScale` (0.1 = mm→cm conversion)
- `FString PythonExecutable` (e.g. `"python3"`)

### `AEventDisplayManager` (AActor)
```
UPROPERTY: UEventDisplayConfig* Config
UPROPERTY: FString CurrentFilePath
UPROPERTY: int32 CurrentEventIndex

UFUNCTION(BlueprintCallable): LoadEDM4HEPFile(FString Path)
  → runs edm4hep_to_json.py via FPlatformProcess::CreateProc(), waits
  → scans output dir for event_*.json, stores list
  → calls LoadEvent(0)

UFUNCTION(BlueprintCallable): LoadNextEvent()
  → CurrentEventIndex++, calls LoadEvent(CurrentEventIndex)

UFUNCTION(BlueprintCallable): LoadEvent(int32 Index)
  → reads event_NNNN.json via UEDMReader::ParseEventJSON()
  → clears old actors, spawns new TrackActors / CaloHitActors / MCParticleActors

Private: TArray<ATrackActor*> TrackActors
         TArray<ACaloHitActor*> CaloHitActors
         TArray<AMCParticleActor*> MCParticleActors
```

### `ATrackActor` (AActor)
- `USplineComponent* Spline`
- `TArray<USplineMeshComponent*> SegmentMeshes`
- `UFUNCTION void SetTrackData(const FEDMTrack& Track, const UEventDisplayConfig* Cfg)`
  - Adds spline points, creates segment meshes between them
  - Sets material instance: Color = pos/neg track color, EmissiveIntensity from momentum
- Material: `MI_Track` (instance of `M_Track`)

### `ACaloHitActor` (AActor)
- One actor **per collection name** (e.g. one for ECal, one for HCal)
- `UInstancedStaticMeshComponent* ISMC` — cube SM_Cube
- `UFUNCTION void SetHits(const TArray<FEDMCaloHit>& Hits, const UEventDisplayConfig* Cfg)`
  - For each hit: add instance transform scaled by energy
  - Set per-instance custom data: energy (for emissive shader)
- Material: `MI_CaloHit` (per-instance emissive intensity via Custom Primitive Data)

### `AMCParticleActor` (AActor)
- `UProceduralMeshComponent* LineMesh`
- Draws thin cylinders from Vertex to EndVertex per particle
- Only shown when `Config->bShowMCParticles == true`

### `AColliderVisCharacter` (ACharacter)
- `USpringArmComponent* CameraBoom`
  - TargetArmLength = 400, bEnableCameraLag = true, CameraLagSpeed = 5
  - bEnableCameraRotationLag = true, CameraRotationLagSpeed = 10
  - bUsePawnControlRotation = true
- `UCameraComponent* FollowCamera` (attached to boom)
- Enhanced Input bindings (looked up by asset name from Content/Input/):
  - `IA_Move` → `void Move(const FInputActionValue&)`
  - `IA_Look` → `void Look(const FInputActionValue&)`
  - `IA_Jump` → `Jump()`
  - `IA_NextEvent` → delegate to EventDisplayManager
  - `IA_OpenMenu` → show/hide WBP_EventMenu
  - `IA_SwitchMode` → switch game mode
- `OnLanded()` → trigger `UCameraShakeBase` (subtle landing shake)
- `bOrientRotationToMovement = true`, `bUseControllerRotationYaw = false`

### `AColliderVisCineCameraActor` (ACineCameraActor)
- Preset: FocalLength=50mm, CurrentAperture=2.8, FocusMethod=Tracking
- Focus target: AEventDisplayManager
- Used in Viz/Movie mode

### `ColliderVisGameMode` / `ColliderVisVizGameMode`
- Explore: DefaultPawnClass = BP_ColliderVisCharacter, bStartPlayersAsSpectators = false
- Viz: DefaultPawnClass = ASpectatorPawn, auto-possess BP_CineCamera, input mapped to cinematic fly-through

---

## Input Assets (Enhanced Input — Content/Input/)

| Asset | Type | Physical Binding | Triggered Action |
|-------|------|-----------------|-----------------|
| `IA_Move` | Vector2D | WASD / L-stick | Character movement |
| `IA_Look` | Vector2D | Mouse XY / R-stick | Camera rotation |
| `IA_Jump` | Bool | Space | Jump |
| `IA_NextEvent` | Bool | **Left Mouse Button** / N | Load next EDM4HEP event |
| `IA_OpenMenu` | Bool | Escape / M | Toggle WBP_EventMenu |
| `IA_SwitchMode` | Bool | F1 | Toggle Explore ↔ Viz mode |
| `IA_ToggleDetectorMenu` | Bool | D | Toggle detector visibility panel |
| `IMC_Default` | Mapping Context | — | All mappings |

---

## Materials

### `M_Track`
- Emissive = `TrackColor` × `EmissiveIntensity` (scalar parameter)
- Two-sided, thin geometry, bloom-visible via Lumen emissive
- Scalar params: `EmissiveIntensity` (0–100), Vector param: `TrackColor`

### `M_CaloHit`
- Emissive = `BaseColor` × `EnergyScale` (driven by custom primitive data[0])
- Slightly translucent, glassy; SSS optional for ECal crystals
- Enables Lumen emissive contribution for ambient glow

### `M_DetectorGeometry`
- Semi-transparent metallic PBR (Roughness≈0.4, Metallic≈0.6, Opacity≈0.6)
- Per-subdetector: tinted instance (ECal=teal, HCal=brown, Tracker=blue, Solenoid=copper)

---

## Rendering Config (`Config/DefaultEngine.ini`)

```ini
[/Script/Engine.RendererSettings]
r.DefaultFeature.Bloom=True
r.DefaultFeature.AmbientOcclusion=True
r.Lumen.Enabled=1
r.GenerateMeshDistanceFields=True
r.SkyAtmosphere=1
r.VolumetricFog=1
r.Shadow.Virtual.Enable=1
r.AntiAliasingMethod=4
r.TemporalAA.Algorithm=1
r.PathTracing=1
r.PostProcessAAQuality=6

[/Script/Engine.Engine]
NearClipPlane=1.0
```

---

## Blueprint Assets (Created in UE Editor after C++ compile)

| Asset | Parent | Notes |
|-------|--------|-------|
| `BP_ColliderVisCharacter` | AColliderVisCharacter | Assign SK_Mannequin mesh, animation BP |
| `BP_EventDisplayManager` | AEventDisplayManager | Set Config data asset ref |
| `BP_CineCamera` | AColliderVisCineCameraActor | Place in level |
| `WBP_EventMenu` | UEventMenuWidget | UMG: file path input, Load/Next buttons, close |
| `DA_EventDisplayConfig` | UEventDisplayConfig | Default values, collection list |
| `DA_DetectorVisibility` | UDetectorVisibilityConfig | Sub-detector entries + tags |
| `WBP_DetectorVisibility` | UUserWidget | Scrollable visibility toggle panel |
| `IMC_Default` | UInputMappingContext | Map all IA_ assets to keys above |
| `ABP_Character` | AnimBlueprint | Locomotion blendspace, jump states |

---

## Sub-Detector Visibility Toggle Menu

Available in **both** Explore and Viz modes. Toggled with **D key**.

### `UDetectorVisibilityConfig` (UDataAsset)
```cpp
USTRUCT(BlueprintType)
struct FSubDetectorEntry {
    UPROPERTY(EditAnywhere) FName Name;          // e.g. "ECalBarrel"
    UPROPERTY(EditAnywhere) bool bVisibleByDefault = true;
    UPROPERTY(EditAnywhere) FLinearColor LabelColor;
    // Tags that StaticMesh actors in the level must have to belong to this group
    UPROPERTY(EditAnywhere) TArray<FName> ActorTags;
};

// On UDetectorVisibilityConfig:
UPROPERTY(EditAnywhere)
TArray<FSubDetectorEntry> SubDetectors;
```

### `ADetectorVisibilityManager` (AActor — placed in level)
```
UPROPERTY: UDetectorVisibilityConfig* Config
UPROPERTY: TMap<FName, TArray<AActor*>> SubDetectorActors  // populated on BeginPlay

UFUNCTION(BlueprintCallable): SetSubDetectorVisible(FName Name, bool bVisible)
  → iterates SubDetectorActors[Name], calls Actor->SetActorHiddenInGame(!bVisible)
  → also toggles render-state via UPrimitiveComponent::SetVisibility for ISMs

UFUNCTION(BlueprintCallable): ToggleSubDetector(FName Name)
UFUNCTION(BlueprintCallable): SetAllVisible(bool bVisible)
UFUNCTION(BlueprintPure):     IsSubDetectorVisible(FName Name) → bool
```

On `BeginPlay`, scans all actors with matching tags and caches them in `SubDetectorActors`.

### `WBP_DetectorVisibility` (UMG Widget)
- Vertical scroll box with one row per `FSubDetectorEntry`:
  - Color swatch + name label
  - Toggle checkbox → calls `DetectorVisibilityManager.SetSubDetectorVisible()`
- "All On" / "All Off" buttons at top
- Added to viewport on BeginPlay; shown/hidden by `IA_ToggleDetectorMenu` (D key)
- Works in both Explore and Viz game modes

---

## Geometry Loading & Static Rendering Optimizations

Detector geometry is **fully static** (no runtime movement or deformation). This enables aggressive optimizations:

### Static Mesh Import
- GLTF files from `ddgeoviztools/test/` imported via **glTF importer plugin** at editor time
- Each sub-detector GLTF → one or more `UStaticMesh` assets
- Actor tags set matching `FSubDetectorEntry.ActorTags` (set in DA_DetectorVisibility)

### Nanite (UE5 Virtualized Geometry)
- Enable Nanite on **all** detector static meshes
- High polygon count from GLTF → Nanite handles LOD automatically, zero manual LODs needed
- `SM_ECalBarrel`, `SM_HCalBarrel`, etc. → enable "Nanite" checkbox in mesh import/editor

### Virtual Shadow Maps
- `r.Shadow.Virtual.Enable=1` in DefaultEngine.ini
- Accurate high-res shadows on all static detector meshes

### Mobility: Static
- All detector `AStaticMeshActor` instances: `Mobility = Static`
- Enables precomputed visibility (GPU occlusion culling baked at editor time)
- Lumen remains active for dynamic lights and emissive event-display objects

### HLOD (optional, for very large detectors)
- Enable Hierarchical LOD proxy meshes for distant camera views
- World Partition streaming is optional but not required for typical detector scale

### Collision
- Detector meshes: `CollisionEnabled = NoCollision` (no physics needed, saves GPU/CPU)
- Character collision uses an invisible simple geometry floor/boundary, not detector mesh

---

## Files to Create

### C++ / Build
All in `Source/ColliderVis/` (compiled by UE build system):
- `ColliderVis.Build.cs`
  - Module deps: `Core, CoreUObject, Engine, InputCore, EnhancedInput, UMG, Json, JsonUtilities, CinematicCamera, ProceduralMeshComponent`
- `ColliderVis.h` — module header
- `EDM4HEPTypes.h`
- `EDM4HEPReader.h` / `EDM4HEPReader.cpp`
- `EventDisplayConfig.h` / `EventDisplayConfig.cpp`
- `EventDisplayManager.h` / `EventDisplayManager.cpp`
- `TrackActor.h` / `TrackActor.cpp`
- `CaloHitActor.h` / `CaloHitActor.cpp`
- `MCParticleActor.h` / `MCParticleActor.cpp`
- `ColliderVisCharacter.h` / `ColliderVisCharacter.cpp`
- `ColliderVisCineCameraActor.h` / `ColliderVisCineCameraActor.cpp`
- `ColliderVisGameMode.h` / `ColliderVisGameMode.cpp`
- `ColliderVisVizGameMode.h` / `ColliderVisVizGameMode.cpp`
- `EventMenuWidget.h` / `EventMenuWidget.cpp`
- `DetectorVisibilityConfig.h` / `DetectorVisibilityConfig.cpp`
- `DetectorVisibilityManager.h` / `DetectorVisibilityManager.cpp`

### Python Tools
- `Tools/edm4hep_to_json.py`
- `Tools/requirements.txt`: `uproot>=5.0, awkward>=2.0, numpy`

### Config
- `Config/DefaultEngine.ini`
- `Config/DefaultGame.ini`
- `Config/DefaultInput.ini`

### Project File
- `ColliderVis.uproject`
  - `"EngineAssociation": "5.7"`
  - Plugins: `EnhancedInput`, `CinematicCamera`, `ProceduralMeshComponent`, `MovieRenderPipeline`, `GLTFExporter` (for GLTF import)

---

## Verification Checklist

1. **Build**: `UnrealBuildTool ColliderVis Development Linux -project=ColliderVis.uproject` — zero errors
2. **Enhanced Input**: confirm `IA_Move`, `IA_Look`, `IA_Jump`, `IA_NextEvent`, `IA_OpenMenu`, `IA_SwitchMode`, `IA_ToggleDetectorMenu` all exist in `Content/Input/`
3. **EDM4HEP converter**: `python Tools/edm4hep_to_json.py test.root /tmp/out/` → produces `event_0000.json` with correct schema
4. **Event loading**: `EventDisplayManager.LoadEDM4HEPFile(path)` via Blueprint → track/hit actors spawn in level
5. **Next event**: Left-click → event index increments, new actors replace old
6. **Runtime menu**: Escape → `WBP_EventMenu` opens, enter new path, click Load → new file converted + event 0 displayed
7. **Mode switch**: F1 → character removed, cine camera activated; F1 again → character returns
8. **Detector visibility**: D → `WBP_DetectorVisibility` opens; uncheck ECalBarrel → ECal meshes hidden in both modes; re-check → reappear
9. **Movie render**: Movie Render Queue with Path Tracer + 64 samples → EXR sequence output
10. **Photo-realism**: HDRI sky + directional light → hard shadows, Lumen emissive glow on tracks/hits, depth-of-field on cine camera
11. **Nanite**: detector SM assets show "Nanite Enabled"; `stat Nanite` shows virtual geometry rendering
12. **Static mobility**: detector actors show `Mobility = Static` in World Outliner

---

## Implementation Notes

- **Start from the UE5 Third Person template** — gives you mannequin mesh, AnimBlueprint, locomotion blendspace, and a working character out of the box. Replace the GameMode and Character C++ parent classes with ColliderVis ones.
- **glTF importer plugin**: must be enabled in Plugins menu before importing GLTF files from `ddgeoviztools`.
- **ddgeoviztools pipeline**: run `split-convert` on your GDML file first to produce per-sub-detector GLTF files, then import those into the UE5 project.
- **Actor tagging**: after importing GLTF meshes and placing actors in the level, use a UE5 Python editor script to batch-set actor tags matching the sub-detector names in `DA_DetectorVisibility`.
- **Movie Render Queue**: enable the `Movie Render Queue` plugin (ships with UE5); configure a preset with Anti-Aliasing (32+ samples), Path Tracer renderer, EXR output.
- **Skill reference**: follow the [Unreal Engine Skill](https://github.com/DSTN2000/claude-unreal-engine-skill) zero-assumptions protocol — always discover IA_/IMC_/BP_ asset paths before referencing them in C++ `LoadObject<>` calls.
