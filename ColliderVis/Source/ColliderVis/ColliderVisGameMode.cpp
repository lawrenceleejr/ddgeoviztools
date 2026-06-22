#include "ColliderVisGameMode.h"
#include "ColliderVisCharacter.h"
#include "ColliderVisHUD.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/DirectionalLight.h"
#include "Engine/RectLight.h"
#include "Engine/SkyLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "EngineUtils.h"   // TActorIterator — detect in-level atmosphere to avoid doubling
#include "Engine/StaticMeshActor.h"
#include "Engine/StaticMesh.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/PlayerController.h"
#include "Components/StaticMeshComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/RectLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Materials/Material.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "UObject/ConstructorHelpers.h"

AColliderVisGameMode::AColliderVisGameMode()
{
	// Use the native character class directly. A BP_ColliderVisCharacter exists, but
	// ConstructorHelpers::FClassFinder for it failed to resolve at CDO-construction
	// time (in commandlets / early load) and always fell back to this class anyway —
	// while spamming a modal "Failed to find ...BP_ColliderVisCharacter_C" error on
	// launch. The C++ class carries the example Mannequin, so this is the same pawn
	// without the error.
	DefaultPawnClass = AColliderVisCharacter::StaticClass();

	HUDClass = AColliderVisHUD::StaticClass();

	// Needed to drive the animated cinematic cameras in Tick().
	PrimaryActorTick.bCanEverTick = true;
}

void AColliderVisGameMode::BeginPlay()
{
	Super::BeginPlay();

	// Always-on: cinematic grade + god-ray volumetric fog + low ambient sky.
	SetupPostProcessAndFog();

	// Default soft/warm cinematic key-fill-rim rig — ON by default so PIE
	// matches the editor render look.  Turn off if a level provides its own
	// authoritative imported lights.
	if (bSpawnDefaultLighting)
	{
		SetupDefaultLightRig();
	}
	if (bSpawnSciFiRoom)
	{
		SpawnSciFiRoom();
	}

	// Dramatic camera coverage (wide-angle, shallow DoF; some animated).
	if (bSpawnCinematicCameras)
	{
		SetupCinematicCameras();
	}
}

void AColliderVisGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (AnimatedCameras.Num() == 0) return;

	CameraAnimTime += DeltaSeconds;
	const FVector Target = CameraTargetLocation;

	// ── Animated camera 0: slow orbit + gentle vertical bob, wide and low ────
	if (ACameraActor* Orbit = AnimatedCameras.IsValidIndex(0) ? AnimatedCameras[0].Get() : nullptr)
	{
		const float Period = 24.f;                              // seconds per revolution
		const float Ang    = (CameraAnimTime / Period) * 2.f * PI;
		const float Radius = 1200.f;
		const float Height = 250.f + 120.f * FMath::Sin(CameraAnimTime * 0.35f);
		// Orbit around the target in world XY, at an absolute world height.
		const FVector Pos(Target.X + Radius * FMath::Cos(Ang),
		                  Target.Y + Radius * FMath::Sin(Ang),
		                  Height);
		Orbit->SetActorLocation(Pos);
		Orbit->SetActorRotation((Target - Pos).Rotation());
	}

	// ── Animated camera 1: dolly-in along +X with a slow arc, eye level ──────
	if (ACameraActor* Dolly = AnimatedCameras.IsValidIndex(1) ? AnimatedCameras[1].Get() : nullptr)
	{
		const float Cycle = 18.f;
		const float T     = 0.5f - 0.5f * FMath::Cos((CameraAnimTime / Cycle) * 2.f * PI); // 0→1→0 ease
		const float Dist  = FMath::Lerp(2600.f, 700.f, T);     // push in then pull back
		const float Side  = 300.f * FMath::Sin(CameraAnimTime * 0.2f);
		const FVector Pos(-Dist, Side, 180.f);
		Dolly->SetActorLocation(Pos);
		Dolly->SetActorRotation((Target - Pos).Rotation());
	}

	// ── Animated camera 2: crane — sweeps from low to high while orbiting ────
	if (ACameraActor* Crane = AnimatedCameras.IsValidIndex(2) ? AnimatedCameras[2].Get() : nullptr)
	{
		const float Period = 30.f;
		const float Ang    = (CameraAnimTime / Period) * 2.f * PI + PI; // opposite side from orbit cam
		const float Radius = 1500.f;
		const float Height = FMath::Lerp(80.f, 1100.f,
		                                 0.5f - 0.5f * FMath::Cos(CameraAnimTime * 0.12f));
		const FVector Pos(Radius * FMath::Cos(Ang), Radius * FMath::Sin(Ang), Height);
		Crane->SetActorLocation(Pos);
		Crane->SetActorRotation((Target - Pos).Rotation());
	}
}

void AColliderVisGameMode::SetupPostProcessAndFog()
{
	UWorld* World = GetWorld();
	if (!World) return;

	// Don't double the authored in-level atmosphere. ColliderVisMain already places a
	// tuned PostProcessVolume, SkyLight and (volumetric) ExponentialHeightFog; spawning
	// duplicates here wastes perf (two volumetric fogs = a major Mac cost) and fights the
	// tuned values. Only spawn the ones the level is missing (e.g. on a blank map).
	auto LevelHas = [World](UClass* Cls) -> bool
	{
		TActorIterator<AActor> It(World, Cls);
		return static_cast<bool>(It);
	};
	const bool bHasPPV      = LevelHas(APostProcessVolume::StaticClass());
	const bool bHasSkyLight = LevelHas(ASkyLight::StaticClass());
	const bool bHasFog      = LevelHas(AExponentialHeightFog::StaticClass());

	// ── Post Process Volume (infinite extent) ───────────────────────────────
	//
	// Cinematic look spec (see GAME_BUILD_PLAN.md § "Cinematic look spec").
	// Warm-leaning teal/orange Hollywood grade applied in C++ so PIE matches
	// the values tuned live on PostProcessVolume_0 in the editor.
	APostProcessVolume* PPV = bHasPPV ? nullptr : World->SpawnActor<APostProcessVolume>();
	if (PPV)
	{
		PPV->bUnbound    = true;
		PPV->BlendWeight = 1.f;

		FPostProcessSettings& S = PPV->Settings;

		// ── Auto Exposure (Histogram) ───────────────────────────────────────
		// Manual-feel histogram metering; physical-camera exposure OFF so the
		// grade is deterministic across shots.
		S.bOverride_AutoExposureMethod = true;
		S.AutoExposureMethod           = AEM_Histogram;
		S.bOverride_AutoExposureMinBrightness = true;
		S.AutoExposureMinBrightness           = 0.03f;
		S.bOverride_AutoExposureMaxBrightness = true;
		S.AutoExposureMaxBrightness           = 2.0f;
		S.bOverride_AutoExposureBias = true;
		S.AutoExposureBias           = 0.6f;
		S.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
		S.AutoExposureApplyPhysicalCameraExposure           = false;

		// ── White balance ───────────────────────────────────────────────────
		// Slightly warm key temperature (5800K) anchors the teal/orange split.
		S.bOverride_WhiteTemp = true;
		S.WhiteTemp           = 5800.f;

		// ── Global tone: gentle saturation + contrast lift ──────────────────
		S.bOverride_ColorSaturation = true;
		S.ColorSaturation           = FVector4(1.06f, 1.06f, 1.06f, 1.0f);
		S.bOverride_ColorContrast = true;
		S.ColorContrast           = FVector4(1.08f, 1.08f, 1.08f, 1.0f);

		// ── Teal / orange split-tone ────────────────────────────────────────
		// Warm highlights (orange), cool teal shadows — the classic Hollywood
		// complementary grade, warm-leaning.
		S.bOverride_ColorGainHighlights = true;
		S.ColorGainHighlights           = FVector4(1.06f, 1.00f, 0.90f, 1.0f);  // warm highs
		S.bOverride_ColorGainShadows = true;
		S.ColorGainShadows           = FVector4(0.94f, 1.00f, 1.08f, 1.0f);     // teal shadows

		// ── Local Exposure ──────────────────────────────────────────────────
		// Soften highlight rolloff so bright fixtures don't clip flat.
		S.bOverride_LocalExposureHighlightContrastScale = true;
		S.LocalExposureHighlightContrastScale           = 0.85f;

		// ── Bloom (SOG) ─────────────────────────────────────────────────────
		S.bOverride_BloomMethod = true;
		S.BloomMethod           = BM_SOG;
		S.bOverride_BloomIntensity = true;
		S.BloomIntensity           = 0.8f;
		S.bOverride_BloomThreshold = true;
		S.BloomThreshold           = 1.0f;

		// ── Lens: chromatic fringe + flare ──────────────────────────────────
		S.bOverride_SceneFringeIntensity = true;
		S.SceneFringeIntensity           = 1.0f;
		S.bOverride_ChromaticAberrationStartOffset = true;
		S.ChromaticAberrationStartOffset           = 0.4f;  // clean center, fringe at edges
		S.bOverride_LensFlareIntensity = true;
		S.LensFlareIntensity           = 0.3f;

		// ── Ambient Occlusion ───────────────────────────────────────────────
		S.bOverride_AmbientOcclusionIntensity = true;
		S.AmbientOcclusionIntensity           = 0.7f;
		S.bOverride_AmbientOcclusionRadius = true;
		S.AmbientOcclusionRadius           = 200.f;
		S.bOverride_AmbientOcclusionPower = true;
		S.AmbientOcclusionPower           = 2.5f;

		// ── Vignette + film grain ───────────────────────────────────────────
		S.bOverride_VignetteIntensity = true;
		S.VignetteIntensity           = 0.45f;
		S.bOverride_FilmGrainIntensity = true;
		S.FilmGrainIntensity           = 0.12f;

		// ── Motion blur ─────────────────────────────────────────────────────
		S.bOverride_MotionBlurAmount = true;
		S.MotionBlurAmount           = 0.4f;

		// ── Depth of Field (cinematic) ──────────────────────────────────────
		// f/2.8 on a 36mm full-frame sensor, focus ~22 m out (collision region).
		S.bOverride_DepthOfFieldFstop = true;
		S.DepthOfFieldFstop           = 2.8f;
		S.bOverride_DepthOfFieldFocalDistance = true;
		S.DepthOfFieldFocalDistance           = 2200.f;
		S.bOverride_DepthOfFieldSensorWidth = true;
		S.DepthOfFieldSensorWidth           = 36.f;

		// ── Lumen GI / reflections ──────────────────────────────────────────
		S.bOverride_ReflectionMethod = true;
		S.ReflectionMethod           = EReflectionMethod::Lumen;
		S.bOverride_LumenReflectionQuality = true;
		S.LumenReflectionQuality           = 2.f;
		S.bOverride_LumenFinalGatherQuality = true;
		S.LumenFinalGatherQuality           = 4.f;
		S.bOverride_LumenMaxTraceDistance = true;
		S.LumenMaxTraceDistance           = 30000.f;
	}

	// NO SkyAtmosphere — an atmosphere would render a sky outside the scene and
	// bleach the geometry with skylight.  Key/fill/rim illumination now comes from
	// the imported Blender light rig placed in the level by Tools/ue5_build_content.py
	// (or, on a blank map, from SetupDefaultLightRig() when bSpawnDefaultLighting is on).

	// ── Sky Light — low neutral ambient fill, no scene capture (no sky exists) ──
	ASkyLight* SkyLightActor = bHasSkyLight ? nullptr : World->SpawnActor<ASkyLight>();
	if (SkyLightActor)
	{
		USkyLightComponent* SLC = SkyLightActor->GetLightComponent();
		SLC->SourceType       = ESkyLightSourceType::SLS_SpecifiedCubemap; // no captured scene
		SLC->Intensity        = 0.35f;   // very low — let the key/fill/rim rig shape the scene
		SLC->bRealTimeCapture = false;
		// Slightly cool, near-neutral ambient — fills shadow regions without
		// fighting the warm key.  The teal/orange split lives in post.
		SLC->LightColor       = FColor(196, 206, 220);
	}

	// ── Exponential Height Fog — INDOOR HAZE ─────────────────────────────────
	//
	// Indoor laboratory haze: low density (so the room is visible), short
	// reach (StartDistance keeps the player's near-field clean), neutral
	// cool tint.  Volumetric scattering ON so the practical rect lights
	// cast visible god-ray shafts through the room.
	AExponentialHeightFog* FogActor = bHasFog ? nullptr : World->SpawnActor<AExponentialHeightFog>();
	if (FogActor)
	{
		UExponentialHeightFogComponent* FC = FogActor->GetComponent();

		FC->FogDensity              = 0.006f;            // light haze, not soup
		FC->FogInscatteringLuminance = FLinearColor(0.05f, 0.07f, 0.10f);
		FC->FogHeightFalloff        = 0.2f;
		FC->StartDistance           = 300.f;
		FC->FogMaxOpacity           = 0.7f;

		FC->bEnableVolumetricFog                 = true;
		FC->VolumetricFogScatteringDistribution  = 0.6f;
		FC->VolumetricFogExtinctionScale         = 1.0f;
		FC->VolumetricFogAlbedo                  = FLinearColor(0.5f, 0.6f, 0.7f).ToFColor(true);
		FC->VolumetricFogEmissive                = FLinearColor(0.001f, 0.0015f, 0.002f);

		// No abyssal second layer — we're in a finite room.
		FC->SecondFogData.FogDensity       = 0.0f;
		FC->SecondFogData.FogHeightFalloff = 0.5f;
		FC->SecondFogData.FogHeightOffset  = -500.f;
	}
}

// ---------------------------------------------------------------------------
// Default cinematic light rig (soft, warm, moody)
//
// A tasteful three-point key / fill / rim setup using large soft rect lights.
// Spawned when bSpawnDefaultLighting is true (now the default) so PIE matches
// the editor render look.  Volumetric scattering on the key and rim pushes
// god-ray shafts through the existing volumetric exponential height fog.
// Intensities are kept moderate so the scene stays moody, not blown out.
// ---------------------------------------------------------------------------
void AColliderVisGameMode::SetupDefaultLightRig()
{
	UWorld* World = GetWorld();
	if (!World) return;

	// Helper: orient an actor's +X toward the world origin (the collision point)
	auto PointAtOrigin = [](AActor* A, const FVector& Pos)
	{
		const FVector Dir = (FVector::ZeroVector - Pos).GetSafeNormal();
		A->SetActorRotation(FRotationMatrix::MakeFromX(Dir).Rotator());
	};

	// ── KEY: large warm soft box, high and off to one side ──────────────────
	// Big source + warm temperature = soft wraparound shadows.  Strong
	// volumetric scattering so it throws visible warm god rays through the fog.
	ARectLight* KeyLight = World->SpawnActor<ARectLight>();
	if (KeyLight)
	{
		const FVector KeyPos(-600.f, -500.f, 1400.f);
		KeyLight->SetActorLocation(KeyPos);
		PointAtOrigin(KeyLight, KeyPos);
		URectLightComponent* C = KeyLight->RectLightComponent;
		C->Intensity                      = 700.f;
		C->bUseTemperature                = true;
		C->Temperature                    = 4000.f;    // warm key (~4000K)
		C->SourceWidth                    = 900.f;     // large → soft shadows
		C->SourceHeight                   = 600.f;
		C->AttenuationRadius              = 5000.f;
		C->SetBarnDoorAngle(60.f);                     // gentle softbox spill
		C->VolumetricScatteringIntensity  = 2.5f;      // warm god rays
	}

	// ── FILL: broad, dim, cool-ish — opens up the shadow side ───────────────
	// Lower intensity than the key (keeps contrast/mood); cooler temperature
	// complements the warm key for a subtle teal/orange separation in-scene.
	// No (or minimal) volumetrics so it doesn't wash out the haze.
	ARectLight* FillLight = World->SpawnActor<ARectLight>();
	if (FillLight)
	{
		const FVector P(200.f, 1000.f, 700.f);
		FillLight->SetActorLocation(P);
		PointAtOrigin(FillLight, P);
		URectLightComponent* C = FillLight->RectLightComponent;
		C->Intensity                      = 220.f;     // ~1/3 of key → preserves shape
		C->bUseTemperature                = true;
		C->Temperature                    = 6200.f;    // cool-ish fill
		C->SourceWidth                    = 1400.f;    // very broad, very soft
		C->SourceHeight                   = 900.f;
		C->AttenuationRadius              = 5000.f;
		C->VolumetricScatteringIntensity  = 0.3f;
	}

	// ── RIM / BACKLIGHT: warm edge separation from behind ───────────────────
	// Tight-ish warm source behind the detector to carve a glowing edge and
	// add a second set of god-ray shafts toward camera.
	ARectLight* RimLight = World->SpawnActor<ARectLight>();
	if (RimLight)
	{
		const FVector RimPos(1000.f, 200.f, 900.f);
		RimLight->SetActorLocation(RimPos);
		PointAtOrigin(RimLight, RimPos);
		URectLightComponent* C = RimLight->RectLightComponent;
		C->Intensity                      = 450.f;
		C->bUseTemperature                = true;
		C->Temperature                    = 4300.f;    // warm rim
		C->SourceWidth                    = 300.f;
		C->SourceHeight                   = 700.f;
		C->AttenuationRadius              = 5000.f;
		C->VolumetricScatteringIntensity  = 3.0f;      // strongest god rays toward camera
	}
}

// ---------------------------------------------------------------------------
// Cinematic camera coverage
//
// Spawns a small set of ACameraActors framing the detector with wide-angle FOV
// and shallow depth of field for dramatic, Hollywood-style views.  Some are
// static "money shots", three are animated (orbit / dolly / crane) in Tick().
// The animated cameras crank up lens flare for streaky highlights as they sweep
// past the practical lights.
//
// Wide-angle + shallow DoF is achieved through each camera's own
// FPostProcessSettings (FOV on the component, physical DoF via Fstop/focal/
// sensor in post) so this needs no CinematicCamera module dependency.  These are
// a working PIE preview and a starting point — the orchestrator can convert them
// to CineCameraActors and bind them into Level Sequences in-editor.
// ---------------------------------------------------------------------------
void AColliderVisGameMode::SetupCinematicCameras()
{
	UWorld* World = GetWorld();
	if (!World) return;

	const FVector Target = CameraTargetLocation;

	// Helper: spawn one camera, aim it at the target, set wide FOV + shallow DoF
	// + lens-flare strength.  Returns the actor so animated ones can be tracked.
	auto SpawnCam = [&](const TCHAR* Label, const FVector& Pos, float FOV,
	                    float FStop, float FocalDistance, float SensorWidth,
	                    float LensFlare) -> ACameraActor*
	{
		ACameraActor* Cam = World->SpawnActor<ACameraActor>(Pos, (Target - Pos).Rotation());
		if (!Cam) return nullptr;
#if WITH_EDITOR
		Cam->SetActorLabel(Label);   // friendly name in the editor outliner (editor-only)
#endif

		UCameraComponent* CC = Cam->GetCameraComponent();
		if (CC)
		{
			// Wide-angle look — large horizontal FOV.
			CC->SetFieldOfView(FOV);

			FPostProcessSettings& P = CC->PostProcessSettings;

			// Shallow, physical depth of field (DoF follows the same f/2.8-style
			// look as the global grade but per-camera, so each shot can rack).
			P.bOverride_DepthOfFieldFstop = true;
			P.DepthOfFieldFstop           = FStop;
			P.bOverride_DepthOfFieldFocalDistance = true;
			P.DepthOfFieldFocalDistance           = FocalDistance;
			P.bOverride_DepthOfFieldSensorWidth = true;
			P.DepthOfFieldSensorWidth           = SensorWidth;

			// Lens flare — subtle on static frames, punchy on the movers.
			P.bOverride_LensFlareIntensity = true;
			P.LensFlareIntensity           = LensFlare;

			// A touch more bloom on cameras so practical lights streak nicely.
			P.bOverride_BloomIntensity = true;
			P.BloomIntensity           = 1.0f;
		}
		return Cam;
	};

	AnimatedCameras.Reset();

	// ── STATIC money shots ──────────────────────────────────────────────────

	// 1) Low wide hero — looking up at the detector, very wide, deep dramatic DoF.
	//    18mm-equivalent feel (FOV ~95) on full-frame, focus on the core.
	SpawnCam(TEXT("Cam_Hero_LowWide"),
	         FVector(-1600.f, -700.f, 120.f),
	         95.f, 2.0f, 1700.f, 36.f, 0.4f);

	// 2) Three-quarter establishing — classic 3/4 high angle, wide, shallow.
	SpawnCam(TEXT("Cam_Establish_ThreeQuarter"),
	         FVector(1400.f, -1200.f, 900.f),
	         85.f, 2.2f, 1900.f, 36.f, 0.35f);

	// 3) Profile detail — tighter (but still wide-ish), very shallow DoF so the
	//    near detector elements melt into bokeh.
	SpawnCam(TEXT("Cam_Profile_Detail"),
	         FVector(0.f, 1300.f, 250.f),
	         70.f, 1.8f, 1300.f, 36.f, 0.3f);

	// 4) Top-down god view — straight down, ultrawide.
	SpawnCam(TEXT("Cam_TopDown_God"),
	         FVector(Target.X, Target.Y, 2600.f),
	         100.f, 4.0f, 2500.f, 36.f, 0.25f);

	// ── ANIMATED shots (driven in Tick) — lens flares dialled up ────────────

	// A) Orbit — slow wide circle, low, with bobbing height.
	if (ACameraActor* C = SpawnCam(TEXT("Cam_Anim_Orbit"),
	                               FVector(1200.f, 0.f, 300.f),
	                               92.f, 2.0f, 1500.f, 36.f, 0.7f))
	{
		AnimatedCameras.Add(C);
	}

	// B) Dolly — pushes in along -X then pulls back, eye level, wide.
	if (ACameraActor* C = SpawnCam(TEXT("Cam_Anim_Dolly"),
	                               FVector(-2600.f, 0.f, 180.f),
	                               88.f, 1.8f, 1800.f, 36.f, 0.8f))
	{
		AnimatedCameras.Add(C);
	}

	// C) Crane — sweeps from low to high while orbiting the far side, widest.
	if (ACameraActor* C = SpawnCam(TEXT("Cam_Anim_Crane"),
	                               FVector(-1500.f, 0.f, 80.f),
	                               98.f, 2.4f, 2000.f, 36.f, 0.9f))
	{
		AnimatedCameras.Add(C);
	}

	// Optionally make the first animated camera the live view (attract / capture).
	if (bUseCinematicCameraAsView && AnimatedCameras.Num() > 0)
	{
		if (APlayerController* PC = World->GetFirstPlayerController())
		{
			PC->SetViewTargetWithBlend(AnimatedCameras[0], 0.5f);
		}
	}

	UE_LOG(LogTemp, Log,
	       TEXT("ColliderVisGameMode: spawned %d cinematic cameras (%d animated)."),
	       4 + AnimatedCameras.Num(), AnimatedCameras.Num());
}

// ---------------------------------------------------------------------------
// Procedural sci-fi room
//
// Spawned at BeginPlay so the level always has something for the third-person
// character to stand on, even if you opened a blank default map.  Uses the
// engine's built-in Plane mesh and a dynamic dark metallic material — no
// content browser assets required.
// ---------------------------------------------------------------------------
void AColliderVisGameMode::SpawnSciFiRoom()
{
	UWorld* World = GetWorld();
	if (!World) return;

	UStaticMesh* PlaneMesh = LoadObject<UStaticMesh>(
		nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
	if (!PlaneMesh)
	{
		UE_LOG(LogTemp, Warning, TEXT("ColliderVisGameMode: /Engine/BasicShapes/Plane "
		                              "not loadable; skipping procedural room."));
		return;
	}

	// Default plane is 100×100 cm at Z=0 facing +Z.  Scale up to room size.
	// Room: 30 m × 30 m × 8 m tall — comfortably encloses a typical
	// 6 m detector with space for the third-person character to walk.
	const float RoomHalf   = 1500.f;     // 15 m half-extent → 30 m room
	const float RoomHeight = 800.f;      //  8 m ceiling

	// Default Engine material (lookup is cheap; failure is fine — actor
	// will just use the engine WorldGrid).
	UMaterialInterface* BaseMat = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/EngineMaterials/M_AssetPlatform.M_AssetPlatform"));

	auto SpawnPanel = [&](FName Name, FVector Location, FRotator Rotation,
	                      float ScaleXY, FLinearColor Tint, float Metallic, float Roughness)
	{
		FActorSpawnParameters Params;
		Params.Name = Name;
		AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(
			AStaticMeshActor::StaticClass(), Location, Rotation, Params);
		if (!Actor) return;
		Actor->SetMobility(EComponentMobility::Static);
		UStaticMeshComponent* SMC = Actor->GetStaticMeshComponent();
		if (!SMC) return;
		SMC->SetStaticMesh(PlaneMesh);
		Actor->SetActorScale3D(FVector(ScaleXY, ScaleXY, 1.f));
		if (BaseMat)
		{
			UMaterialInstanceDynamic* MID = UMaterialInstanceDynamic::Create(BaseMat, Actor);
			if (MID)
			{
				MID->SetVectorParameterValue(TEXT("Color"),     Tint);
				MID->SetVectorParameterValue(TEXT("BaseColor"), Tint);
				MID->SetScalarParameterValue(TEXT("Metallic"),  Metallic);
				MID->SetScalarParameterValue(TEXT("Roughness"), Roughness);
				SMC->SetMaterial(0, MID);
			}
		}
		// Tag so DetectorVisibilityManager can opt these out of toggles
		Actor->Tags.Add(TEXT("SciFiRoom"));
	};

	const float RoomXY = RoomHalf / 50.f;   // Plane.Plane is 100 cm, so XY scale = half/50

	// Floor — gunmetal, smooth-but-not-mirror
	SpawnPanel(TEXT("SciFi_Floor"),
	           FVector(0.f, 0.f, -200.f),
	           FRotator::ZeroRotator,
	           RoomXY,
	           FLinearColor(0.04f, 0.05f, 0.06f), 0.6f, 0.35f);

	// Ceiling — even darker, more matte; needs to be flipped to face down
	SpawnPanel(TEXT("SciFi_Ceiling"),
	           FVector(0.f, 0.f, RoomHeight),
	           FRotator(180.f, 0.f, 0.f),
	           RoomXY,
	           FLinearColor(0.02f, 0.025f, 0.035f), 0.3f, 0.7f);

	// Four walls — slightly bluer than floor, brushed-feel roughness
	const FLinearColor WallTint(0.05f, 0.06f, 0.08f);
	const float        Metallic  = 0.4f;
	const float        Roughness = 0.55f;
	const float        WallH     = RoomHeight / 100.f; // for Z-scale on rotated planes
	const float        WallScale = RoomXY;             // matches floor

	// +X wall (faces −X)
	SpawnPanel(TEXT("SciFi_Wall_PosX"),
	           FVector( RoomHalf, 0.f, RoomHeight * 0.5f),
	           FRotator(0.f, 0.f, 90.f),                 // tip plane onto XZ
	           WallScale, WallTint, Metallic, Roughness);
	// −X wall
	SpawnPanel(TEXT("SciFi_Wall_NegX"),
	           FVector(-RoomHalf, 0.f, RoomHeight * 0.5f),
	           FRotator(0.f, 0.f, -90.f),
	           WallScale, WallTint, Metallic, Roughness);
	// +Y wall
	SpawnPanel(TEXT("SciFi_Wall_PosY"),
	           FVector(0.f,  RoomHalf, RoomHeight * 0.5f),
	           FRotator(90.f, 0.f, 0.f),
	           WallScale, WallTint, Metallic, Roughness);
	// −Y wall
	SpawnPanel(TEXT("SciFi_Wall_NegY"),
	           FVector(0.f, -RoomHalf, RoomHeight * 0.5f),
	           FRotator(-90.f, 0.f, 0.f),
	           WallScale, WallTint, Metallic, Roughness);

	UE_LOG(LogTemp, Log,
	       TEXT("ColliderVisGameMode: spawned sci-fi room (%.0fm × %.0fm × %.0fm)"),
	       RoomHalf * 2.f / 100.f, RoomHalf * 2.f / 100.f, RoomHeight / 100.f);
}
