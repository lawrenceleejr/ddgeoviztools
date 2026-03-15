#include "ColliderVisGameMode.h"
#include "ColliderVisCharacter.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/DirectionalLight.h"
#include "Engine/RectLight.h"
#include "Engine/SkyLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkyAtmosphere.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/RectLightComponent.h"
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

		// Bloom — emissive tracks and calo hits should glow visibly
		S.bOverride_BloomIntensity = true;
		S.BloomIntensity           = 1.2f;       // was 0.7
		S.bOverride_BloomMethod    = true;
		S.BloomMethod              = BM_SOG;     // sum-of-gaussians
		S.bOverride_BloomThreshold = true;
		S.BloomThreshold           = -1.0f;      // all luminance contributes, no cut-off

		// Exposure
		S.bOverride_AutoExposureMinBrightness = true;
		S.AutoExposureMinBrightness           = 0.125f;
		S.bOverride_AutoExposureMaxBrightness = true;
		S.AutoExposureMaxBrightness           = 4.f;

		// Vignette
		S.bOverride_VignetteIntensity = true;
		S.VignetteIntensity           = 0.4f;

		// Chromatic aberration — visible lens fringing on high-contrast edges
		S.bOverride_SceneFringeIntensity = true;
		S.SceneFringeIntensity           = 1.2f;   // was 0.3

		// Film grain
		S.bOverride_FilmGrainIntensity = true;
		S.FilmGrainIntensity           = 0.25f;

		// Color grading: slight blue-teal push for physics lab feel
		S.bOverride_ColorGain           = true;
		S.ColorGain                     = FVector4(0.95f, 0.98f, 1.05f, 1.0f);
		S.bOverride_ColorGainHighlights = true;
		S.ColorGainHighlights           = FVector4(0.92f, 0.97f, 1.08f, 1.0f);

		// Depth of Field — deliberately NOT overridden here.
		// UCineCameraComponent drives focal distance per-tick via UpdateFocusToCentroid();
		// a static PPV override at blend weight 1.0 would freeze focus at a fixed distance.

		// Ambient Occlusion — adds contact shadows in detector crevices
		S.bOverride_AmbientOcclusionIntensity = true;
		S.AmbientOcclusionIntensity           = 0.8f;
		S.bOverride_AmbientOcclusionRadius    = true;
		S.AmbientOcclusionRadius              = 200.f;   // ~2 m, matches detector scale

		// Motion blur — visible trailing on fast camera and event transitions
		S.bOverride_MotionBlurAmount = true;
		S.MotionBlurAmount           = 0.5f;
		S.bOverride_MotionBlurMax    = true;
		S.MotionBlurMax              = 0.5f;     // was 0.15
	}

	// --- Sky Atmosphere ---
	World->SpawnActor<ASkyAtmosphere>();

	// --- Directional Light (sky atmosphere driver only — very dim fill) ---
	ADirectionalLight* DirLight = World->SpawnActor<ADirectionalLight>();
	if (DirLight)
	{
		UDirectionalLightComponent* DLC = DirLight->GetComponent();
		DLC->Intensity           = 1.0f;          // dim fill; rect lights are primary
		DLC->bUseTemperature     = true;
		DLC->Temperature         = 5600.f;        // daylight white, atmosphere-compatible
		DLC->bAtmosphereSunLight = true;
		DirLight->SetActorRotation(FRotator(-45.f, 30.f, 0.f));
	}

	// Helper: point an actor's +X axis toward the world origin
	auto PointAtOrigin = [](AActor* A, const FVector& Pos)
	{
		const FVector Dir = (FVector::ZeroVector - Pos).GetSafeNormal();
		A->SetActorRotation(FRotationMatrix::MakeFromX(Dir).Rotator());
	};

	// --- Key light: large warm soft box overhead-left ---
	ARectLight* KeyLight = World->SpawnActor<ARectLight>();
	if (KeyLight)
	{
		const FVector KeyPos(-400.f, 0.f, 1200.f);
		KeyLight->SetActorLocation(KeyPos);
		PointAtOrigin(KeyLight, KeyPos);
		URectLightComponent* KLC = KeyLight->GetRectLightComponent();
		KLC->Intensity         = 2000.f;    // lux
		KLC->bUseTemperature   = true;
		KLC->Temperature       = 4200.f;    // warm daylight
		KLC->SourceWidth       = 300.f;     // 3 m wide — very soft shadows
		KLC->SourceHeight      = 200.f;
		KLC->AttenuationRadius = 3000.f;
	}

	// --- Fill light: cooler, side-angle soft box ---
	ARectLight* FillLight = World->SpawnActor<ARectLight>();
	if (FillLight)
	{
		const FVector FillPos(500.f, 300.f, 700.f);
		FillLight->SetActorLocation(FillPos);
		PointAtOrigin(FillLight, FillPos);
		URectLightComponent* FLC = FillLight->GetRectLightComponent();
		FLC->Intensity         = 800.f;
		FLC->bUseTemperature   = true;
		FLC->Temperature       = 4800.f;    // cooler fill
		FLC->SourceWidth       = 150.f;
		FLC->SourceHeight      = 150.f;
		FLC->AttenuationRadius = 2500.f;
	}

	// --- Rim light: tight cool-white backlight for detector edge separation ---
	ARectLight* RimLight = World->SpawnActor<ARectLight>();
	if (RimLight)
	{
		const FVector RimPos(-300.f, -600.f, 900.f);
		RimLight->SetActorLocation(RimPos);
		PointAtOrigin(RimLight, RimPos);
		URectLightComponent* RLC = RimLight->GetRectLightComponent();
		RLC->Intensity         = 400.f;
		RLC->bUseTemperature   = true;
		RLC->Temperature       = 6000.f;    // cool highlight rim
		RLC->SourceWidth       = 80.f;
		RLC->SourceHeight      = 150.f;
		RLC->AttenuationRadius = 2000.f;
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
		FC->FogDensity           = 0.008f;   // slightly thinner — sense of depth, not fog
		FC->FogInscatteringColor = FLinearColor(0.06f, 0.07f, 0.10f); // pale blue-gray mist
		FC->FogHeightFalloff    = 0.2f;
		FC->StartDistance       = 500.f;    // mist begins 5 m out, clear near the camera
		FC->FogMaxOpacity       = 0.9f;
		FC->bVolumetricFog      = true;
		FC->VolumetricFogScatteringDistribution = 0.2f;
	}
}
