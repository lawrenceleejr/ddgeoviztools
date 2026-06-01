#include "ColliderVisGameMode.h"
#include "ColliderVisCharacter.h"
#include "ColliderVisHUD.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/DirectionalLight.h"
#include "Engine/RectLight.h"
#include "Engine/SkyLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/StaticMesh.h"
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
	// Prefer the BP character (created by Tools/ue5_build_content.py) so any
	// Blueprint-level tweaks apply; both it and the C++ class carry the example
	// Mannequin model.  Falls back to the C++ class if the BP isn't present yet.
	// (.Get() yields UClass* on both arms so the ternary type is unambiguous.)
	static ConstructorHelpers::FClassFinder<AColliderVisCharacter> CharacterBP(
		TEXT("/Game/Blueprints/BP_ColliderVisCharacter"));
	DefaultPawnClass = CharacterBP.Succeeded()
		? CharacterBP.Class.Get()
		: AColliderVisCharacter::StaticClass();

	HUDClass = AColliderVisHUD::StaticClass();
}

void AColliderVisGameMode::BeginPlay()
{
	Super::BeginPlay();

	// Always-on: cinematic grade + god-ray volumetric fog + low ambient sky.
	SetupPostProcessAndFog();

	// Legacy hardcoded rig — OFF by default.  The imported Blender lights and
	// detector geometry placed by Tools/ue5_build_content.py are authoritative.
	if (bSpawnDefaultLighting)
	{
		SetupDefaultLightRig();
	}
	if (bSpawnSciFiRoom)
	{
		SpawnSciFiRoom();
	}
}

void AColliderVisGameMode::SetupPostProcessAndFog()
{
	UWorld* World = GetWorld();
	if (!World) return;

	// ── Post Process Volume (infinite extent) ───────────────────────────────
	APostProcessVolume* PPV = World->SpawnActor<APostProcessVolume>();
	if (PPV)
	{
		PPV->bUnbound    = true;
		PPV->BlendWeight = 1.f;

		FPostProcessSettings& S = PPV->Settings;

		// Lumen — push quality up so the emissive tracks illuminate the detector
		S.bOverride_LumenSceneDetail        = true;
		S.LumenSceneDetail                  = 2.f;    // was 1 — more geometry detail
		S.bOverride_LumenFinalGatherQuality = true;
		S.LumenFinalGatherQuality           = 8.f;    // was 4 — higher bounce quality
		S.bOverride_LumenMaxTraceDistance   = true;
		S.LumenMaxTraceDistance             = 30000.f;

		// Bloom — particle tracks should glow hard.  BM_SOG gives layered halos;
		// for true lens convolution swap to BM_Convolution + add a bloom texture
		// (see UE5_SETUP.md § Advanced Rendering → Bloom Convolution).
		S.bOverride_BloomIntensity = true;
		S.BloomIntensity           = 2.5f;    // was 1.2 — dramatic emissive glow
		S.bOverride_BloomMethod    = true;
		S.BloomMethod              = BM_SOG;
		S.bOverride_BloomThreshold = true;
		S.BloomThreshold           = -1.0f;   // all luminance contributes

		// Exposure — tight range so void stays dark and tracks pop
		S.bOverride_AutoExposureMinBrightness = true;
		S.AutoExposureMinBrightness           = 0.05f;  // was 0.125 — allow deep darks
		S.bOverride_AutoExposureMaxBrightness = true;
		S.AutoExposureMaxBrightness           = 3.f;

		// Vignette — draws the eye toward the detector center
		S.bOverride_VignetteIntensity = true;
		S.VignetteIntensity           = 0.55f;  // was 0.4

		// Chromatic aberration — glass-like lens fringing on track edges
		S.bOverride_SceneFringeIntensity = true;
		S.SceneFringeIntensity           = 1.2f;

		// Film grain — adds quantum-noise texture to the void
		S.bOverride_FilmGrainIntensity = true;
		S.FilmGrainIntensity           = 0.3f;

		// ── Color grading: void black + teal mid + warm emissive highlights ──
		//
		// Shadows → crushed blue-black void (anything not directly lit disappears)
		S.bOverride_ColorGainShadows = true;
		S.ColorGainShadows           = FVector4(0.6f, 0.65f, 0.85f, 1.0f);
		S.bOverride_ColorContrastShadows = true;
		S.ColorContrastShadows           = FVector4(1.5f, 1.5f, 1.5f, 1.0f);

		// Sci-fi indoor palette — cool teal/cyan dominant, with subtle warm
		// accents from the practical lights.  Reads like "inside a clean
		// laboratory hall" rather than "floating in the abyss".
		S.bOverride_ColorGain = true;
		S.ColorGain           = FVector4(0.88f, 0.98f, 1.10f, 1.0f);
		S.bOverride_ColorSaturationMidtones = true;
		S.ColorSaturationMidtones           = FVector4(1.f, 1.f, 1.f, 0.90f);  // light desaturation

		// Highlights — pushed slightly toward cool cyan-white so the indoor
		// fixture light reads as fluorescent / LED rather than tungsten.
		S.bOverride_ColorGainHighlights = true;
		S.ColorGainHighlights           = FVector4(0.95f, 1.02f, 1.10f, 1.0f);

		// Global contrast boost — deepens blacks, brightens track glow
		S.bOverride_ColorContrast = true;
		S.ColorContrast           = FVector4(1.25f, 1.25f, 1.25f, 1.0f);

		// Ambient Occlusion — contact shadows inside detector crevices
		S.bOverride_AmbientOcclusionIntensity = true;
		S.AmbientOcclusionIntensity           = 1.0f;    // was 0.8
		S.bOverride_AmbientOcclusionRadius    = true;
		S.AmbientOcclusionRadius              = 250.f;

		// Motion blur
		S.bOverride_MotionBlurAmount = true;
		S.MotionBlurAmount           = 0.5f;
		S.bOverride_MotionBlurMax    = true;
		S.MotionBlurMax              = 0.5f;

		// Depth of Field — NOT overridden (cine camera drives this via UpdateFocusToCentroid)
	}

	// NO SkyAtmosphere — an atmosphere would render a sky outside the scene and
	// bleach the geometry with skylight.  Key/fill/rim illumination now comes from
	// the imported Blender light rig placed in the level by Tools/ue5_build_content.py
	// (or, on a blank map, from SetupDefaultLightRig() when bSpawnDefaultLighting is on).

	// ── Sky Light — low ambient cyan tint, no scene capture (no sky exists) ──
	ASkyLight* SkyLightActor = World->SpawnActor<ASkyLight>();
	if (SkyLightActor)
	{
		USkyLightComponent* SLC = SkyLightActor->GetLightComponent();
		SLC->SourceType       = ESkyLightSourceType::SLS_SpecifiedCubemap; // no captured scene
		SLC->Intensity        = 0.4f;
		SLC->bRealTimeCapture = false;
		// Cool cyan ambient — fills shadow regions with subtle sci-fi tint
		SLC->LightColor       = FColor(180, 210, 230);
	}

	// ── Exponential Height Fog — INDOOR HAZE ─────────────────────────────────
	//
	// Indoor laboratory haze: low density (so the room is visible), short
	// reach (StartDistance keeps the player's near-field clean), neutral
	// cool tint.  Volumetric scattering ON so the practical rect lights
	// cast visible god-ray shafts through the room.
	AExponentialHeightFog* FogActor = World->SpawnActor<AExponentialHeightFog>();
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
// Legacy default light rig
//
// The original hardcoded "clean-room" four-rect-light setup.  Superseded by the
// imported Blender light rig (placed in the level by Tools/ue5_build_content.py),
// so it is only spawned when bSpawnDefaultLighting is enabled — handy for a blank
// map that has no imported lights.
// ---------------------------------------------------------------------------
void AColliderVisGameMode::SetupDefaultLightRig()
{
	UWorld* World = GetWorld();
	if (!World) return;

	// Helper: orient an actor's +X toward the world origin
	auto PointAtOrigin = [](AActor* A, const FVector& Pos)
	{
		const FVector Dir = (FVector::ZeroVector - Pos).GetSafeNormal();
		A->SetActorRotation(FRotationMatrix::MakeFromX(Dir).Rotator());
	};

	// ── Key light: warm ceiling fixture above the detector ──
	ARectLight* KeyLight = World->SpawnActor<ARectLight>();
	if (KeyLight)
	{
		const FVector KeyPos(-400.f, 0.f, 1500.f);
		KeyLight->SetActorLocation(KeyPos);
		PointAtOrigin(KeyLight, KeyPos);
		URectLightComponent* KLC = KeyLight->RectLightComponent;
		KLC->Intensity         = 800.f;
		KLC->bUseTemperature   = true;
		KLC->Temperature       = 4400.f;
		KLC->SourceWidth       = 500.f;
		KLC->SourceHeight      = 300.f;
		KLC->AttenuationRadius = 4000.f;
	}

	// ── Cool cyan side panel (left wall) ──
	ARectLight* SideLeft = World->SpawnActor<ARectLight>();
	if (SideLeft)
	{
		const FVector P(0.f, -900.f, 600.f);
		SideLeft->SetActorLocation(P);
		PointAtOrigin(SideLeft, P);
		URectLightComponent* C = SideLeft->RectLightComponent;
		C->Intensity         = 300.f;
		C->bUseTemperature   = true;
		C->Temperature       = 7000.f;     // cool cyan
		C->SourceWidth       = 1200.f;     // tall narrow strip on the wall
		C->SourceHeight      = 80.f;
		C->AttenuationRadius = 3000.f;
	}

	// ── Cool cyan side panel (right wall) ──
	ARectLight* SideRight = World->SpawnActor<ARectLight>();
	if (SideRight)
	{
		const FVector P(0.f, 900.f, 600.f);
		SideRight->SetActorLocation(P);
		PointAtOrigin(SideRight, P);
		URectLightComponent* C = SideRight->RectLightComponent;
		C->Intensity         = 300.f;
		C->bUseTemperature   = true;
		C->Temperature       = 7000.f;
		C->SourceWidth       = 1200.f;
		C->SourceHeight      = 80.f;
		C->AttenuationRadius = 3000.f;
	}

	// ── Rim accent (back wall) ──
	ARectLight* RimLight = World->SpawnActor<ARectLight>();
	if (RimLight)
	{
		const FVector RimPos(900.f, 0.f, 800.f);
		RimLight->SetActorLocation(RimPos);
		PointAtOrigin(RimLight, RimPos);
		URectLightComponent* C = RimLight->RectLightComponent;
		C->Intensity         = 250.f;
		C->bUseTemperature   = true;
		C->Temperature       = 6500.f;
		C->SourceWidth       = 200.f;
		C->SourceHeight      = 600.f;
		C->AttenuationRadius = 3000.f;
	}
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
