#include "ColliderVisGameMode.h"
#include "ColliderVisCharacter.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/DirectionalLight.h"
#include "Engine/SkyLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkyAtmosphere.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"

AColliderVisGameMode::AColliderVisGameMode()
{
	DefaultPawnClass = AColliderVisCharacter::StaticClass();
}

void AColliderVisGameMode::BeginPlay()
{
	Super::BeginPlay();
	SetupAtmosphere();
}

void AColliderVisGameMode::SetupAtmosphere()
{
	UWorld* World = GetWorld();
	if (!World) return;

	// --- Post Process Volume (infinite extent) ---
	APostProcessVolume* PPV = World->SpawnActor<APostProcessVolume>();
	if (PPV)
	{
		PPV->bUnbound = true;   // infinite extent
		PPV->BlendWeight = 1.f;

		FPostProcessSettings& S = PPV->Settings;

		// Lumen
		S.bOverride_LumenSceneDetail        = true;
		S.LumenSceneDetail                  = 1.f;
		S.bOverride_LumenFinalGatherQuality = true;
		S.LumenFinalGatherQuality           = 4.f;
		S.bOverride_LumenMaxTraceDistance   = true;
		S.LumenMaxTraceDistance             = 30000.f;

		// Bloom (convolution approximation of starburst)
		S.bOverride_BloomIntensity = true;
		S.BloomIntensity           = 0.7f;
		S.bOverride_BloomMethod    = true;
		S.BloomMethod              = BM_SOG;   // sum-of-gaussians

		// Exposure
		S.bOverride_AutoExposureMinBrightness = true;
		S.AutoExposureMinBrightness           = 0.125f;   // ~3 EV under
		S.bOverride_AutoExposureMaxBrightness = true;
		S.AutoExposureMaxBrightness           = 4.f;

		// Vignette
		S.bOverride_VignetteIntensity = true;
		S.VignetteIntensity           = 0.4f;

		// Chromatic aberration (subtle lens fringing)
		S.bOverride_SceneFringeIntensity = true;
		S.SceneFringeIntensity           = 0.3f;

		// Film grain (cinematic texture)
		S.bOverride_FilmGrainIntensity = true;
		S.FilmGrainIntensity           = 0.3f;

		// Color grading: slight blue-teal push for physics lab feel
		S.bOverride_ColorGain       = true;
		S.ColorGain                 = FVector4(0.95f, 0.98f, 1.05f, 1.0f);
		S.bOverride_ColorGainHighlights = true;
		S.ColorGainHighlights       = FVector4(0.92f, 0.97f, 1.08f, 1.0f);

		// Depth of Field (Bokeh/Gaussian)
		S.bOverride_DepthOfFieldFocalDistance = true;
		S.DepthOfFieldFocalDistance           = 500.f;
		S.bOverride_DepthOfFieldFstop         = true;
		S.DepthOfFieldFstop                   = 2.8f;
		S.bOverride_DepthOfFieldSensorWidth   = true;
		S.DepthOfFieldSensorWidth             = 36.f;

		// Motion blur
		S.bOverride_MotionBlurAmount = true;
		S.MotionBlurAmount           = 0.5f;
		S.bOverride_MotionBlurMax    = true;
		S.MotionBlurMax              = 0.15f;
	}

	// --- Sky Atmosphere ---
	World->SpawnActor<ASkyAtmosphere>();

	// --- Directional Light (sun / lab overhead) ---
	ADirectionalLight* DirLight = World->SpawnActor<ADirectionalLight>();
	if (DirLight)
	{
		UDirectionalLightComponent* DLC = DirLight->GetComponent();
		DLC->Intensity           = 5.f;           // 5 lux — dim lab light
		DLC->LightColor          = FColor(255, 252, 230); // warm white 6500K
		DLC->bAtmosphereSunLight = true;
		DirLight->SetActorRotation(FRotator(-45.f, 30.f, 0.f));
	}

	// --- Sky Light (HDRI ambient — dark "underground lab" feel) ---
	ASkyLight* SkyLightActor = World->SpawnActor<ASkyLight>();
	if (SkyLightActor)
	{
		USkyLightComponent* SLC = SkyLightActor->GetLightComponent();
		SLC->SourceType   = ESkyLightSourceType::SLS_CapturedScene;
		SLC->Intensity    = 0.3f;     // very low ambient, emissives dominate
		SLC->bRealTimeCapture = false;
	}

	// --- Exponential Height Fog (blue-purple particle physics atmosphere) ---
	AExponentialHeightFog* FogActor = World->SpawnActor<AExponentialHeightFog>();
	if (FogActor)
	{
		UExponentialHeightFogComponent* FC = FogActor->GetComponent();
		FC->FogDensity          = 0.01f;
		FC->FogInscatteringColor = FLinearColor(0.05f, 0.04f, 0.12f);
		FC->FogHeightFalloff    = 0.2f;
		FC->StartDistance       = 100.f;
		FC->FogMaxOpacity       = 0.9f;
		FC->bVolumetricFog      = true;
		FC->VolumetricFogScatteringDistribution = 0.2f;
	}
}
