#include "ColliderVisGameMode.h"
#include "ColliderVisCharacter.h"
#include "ColliderVisHUD.h"
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
	HUDClass         = AColliderVisHUD::StaticClass();
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

		// Midtones → teal/cyan push for the "inside a scientific instrument" feel
		S.bOverride_ColorGain = true;
		S.ColorGain           = FVector4(0.82f, 0.92f, 1.18f, 1.0f);
		S.bOverride_ColorSaturationMidtones = true;
		S.ColorSaturationMidtones           = FVector4(1.f, 1.f, 1.f, 0.82f);  // slight desaturation

		// Highlights → warm gold-white so glowing tracks read against cool void
		S.bOverride_ColorGainHighlights = true;
		S.ColorGainHighlights           = FVector4(1.12f, 1.05f, 0.90f, 1.0f);

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

	// ── Sky Atmosphere ───────────────────────────────────────────────────────
	// Kept for volumetric fog compatibility.  The directional light is set to
	// near-zero intensity below so the sky produces no visible colour contribution.
	World->SpawnActor<ASkyAtmosphere>();

	// ── Directional Light — near zero; just enough to keep the atmosphere pipeline
	//    active.  Rect lights + Lumen GI from emissive tracks are the real sources.
	ADirectionalLight* DirLight = World->SpawnActor<ADirectionalLight>();
	if (DirLight)
	{
		if (UDirectionalLightComponent* DLC = Cast<UDirectionalLightComponent>(DirLight->GetLightComponent()))
		{
			DLC->Intensity           = 0.05f;   // was 1.0 — near-zero; void has no sun
			DLC->bUseTemperature     = true;
			DLC->Temperature         = 5600.f;
			DLC->bAtmosphereSunLight = true;
		}
		DirLight->SetActorRotation(FRotator(-45.f, 30.f, 0.f));
	}

	// Helper: orient an actor's +X toward the world origin
	auto PointAtOrigin = [](AActor* A, const FVector& Pos)
	{
		const FVector Dir = (FVector::ZeroVector - Pos).GetSafeNormal();
		A->SetActorRotation(FRotationMatrix::MakeFromX(Dir).Rotator());
	};

	// ── Key light — dimmed vs. studio setup; emissives do the heavy lifting ─
	ARectLight* KeyLight = World->SpawnActor<ARectLight>();
	if (KeyLight)
	{
		const FVector KeyPos(-400.f, 0.f, 1200.f);
		KeyLight->SetActorLocation(KeyPos);
		PointAtOrigin(KeyLight, KeyPos);
		// ARectLight exposes the URectLightComponent as a public field
		// (UPROPERTY BlueprintReadOnly) rather than via a getter — there is
		// no ARectLight::GetRectLightComponent() in UE 5.4.
		URectLightComponent* KLC = KeyLight->RectLightComponent;
		KLC->Intensity         = 400.f;    // was 2000 — void is dark; tracks glow
		KLC->bUseTemperature   = true;
		KLC->Temperature       = 4600.f;   // slightly cooler for void feel
		KLC->SourceWidth       = 300.f;
		KLC->SourceHeight      = 200.f;
		KLC->AttenuationRadius = 3000.f;
	}

	// ── Fill light — barely-there; prevents total blackout of shadowed faces ─
	ARectLight* FillLight = World->SpawnActor<ARectLight>();
	if (FillLight)
	{
		const FVector FillPos(500.f, 300.f, 700.f);
		FillLight->SetActorLocation(FillPos);
		PointAtOrigin(FillLight, FillPos);
		URectLightComponent* FLC = FillLight->RectLightComponent;
		FLC->Intensity         = 150.f;    // was 800
		FLC->bUseTemperature   = true;
		FLC->Temperature       = 5200.f;
		FLC->SourceWidth       = 150.f;
		FLC->SourceHeight      = 150.f;
		FLC->AttenuationRadius = 2500.f;
	}

	// ── Rim light — cool white edge separation; stops detector merging with void
	ARectLight* RimLight = World->SpawnActor<ARectLight>();
	if (RimLight)
	{
		const FVector RimPos(-300.f, -600.f, 900.f);
		RimLight->SetActorLocation(RimPos);
		PointAtOrigin(RimLight, RimPos);
		URectLightComponent* RLC = RimLight->RectLightComponent;
		RLC->Intensity         = 250.f;   // was 400 — keep as distinct accent
		RLC->bUseTemperature   = true;
		RLC->Temperature       = 6500.f;  // cold blue-white for rim
		RLC->SourceWidth       = 80.f;
		RLC->SourceHeight      = 150.f;
		RLC->AttenuationRadius = 2000.f;
	}

	// ── Under-glow — deep blue-violet from below; suggests infinite abyss
	ARectLight* UnderLight = World->SpawnActor<ARectLight>();
	if (UnderLight)
	{
		const FVector UnderPos(0.f, 0.f, -1400.f);
		UnderLight->SetActorLocation(UnderPos);
		PointAtOrigin(UnderLight, UnderPos);   // points upward toward origin
		URectLightComponent* ULC = UnderLight->RectLightComponent;
		ULC->Intensity         = 120.f;
		ULC->bUseTemperature   = true;
		ULC->Temperature       = 8000.f;   // deep cold blue-violet
		ULC->SourceWidth       = 600.f;    // very wide → diffuse upwelling glow
		ULC->SourceHeight      = 600.f;
		ULC->AttenuationRadius = 3500.f;
	}

	// ── Sky Light — near-zero ambient; the void should not have an ambient sky ─
	ASkyLight* SkyLightActor = World->SpawnActor<ASkyLight>();
	if (SkyLightActor)
	{
		USkyLightComponent* SLC = SkyLightActor->GetLightComponent();
		SLC->SourceType       = ESkyLightSourceType::SLS_CapturedScene;
		SLC->Intensity        = 0.05f;   // was 0.3 — almost nothing
		SLC->bRealTimeCapture = false;
	}

	// ── Exponential Height Fog — two-layer ethereal void ─────────────────────
	//
	// Layer 1 (upper/uniform):  thin indigo mist that wraps the whole scene
	//   uniformly (very low HeightFalloff).  The detector floats in it.
	// Layer 2 (lower/dense):    heavy black-blue void beneath the detector —
	//   looking down the bottom disappears into nothing.
	//
	// VolumetricFogScatteringDistribution=0.85 (strongly forward) means bright
	// emissive track segments scatter light forward through the fog as visible
	// god-ray halos — a free effect with no extra cost.
	AExponentialHeightFog* FogActor = World->SpawnActor<AExponentialHeightFog>();
	if (FogActor)
	{
		UExponentialHeightFogComponent* FC = FogActor->GetComponent();

		// ── Layer 1: uniform indigo mist ──────────────────────────────────
		FC->FogDensity              = 0.02f;                              // was 0.008
		// FogInscatteringColor was renamed to FogInscatteringLuminance in
		// UE 5.x; the old field is now FogInscatteringColor_DEPRECATED and
		// no longer assignable from new code.  Display name in the editor
		// is still "Fog Inscattering Color" so the in-engine UI is unchanged.
		FC->FogInscatteringLuminance = FLinearColor(0.012f, 0.010f, 0.045f); // deep indigo-black
		FC->FogHeightFalloff        = 0.04f;   // was 0.2 — very low → uniform regardless of height
		FC->StartDistance           = 150.f;   // was 500 — mist begins 1.5 m from camera
		FC->FogMaxOpacity           = 1.0f;    // complete fadeout at extreme distance

		// Volumetric: strong forward scatter → emissive god-ray halos
		FC->bEnableVolumetricFog                 = true;
		FC->VolumetricFogScatteringDistribution  = 0.85f;  // was 0.2
		FC->VolumetricFogExtinctionScale         = 2.0f;   // more absorptive (darker void)
		// VolumetricFogAlbedo is FColor (8-bit per channel) in UE 5.4, NOT
		// FLinearColor.  Convert from the intended dark blue-violet linear
		// values via FLinearColor::ToFColor(true) — true applies the sRGB
		// curve so the in-engine appearance matches the linear-space intent.
		FC->VolumetricFogAlbedo                  = FLinearColor(0.08f, 0.08f, 0.15f).ToFColor(true);
		// Subtle self-luminance of the void — faint bioluminescent blue-teal haze
		FC->VolumetricFogEmissive                = FLinearColor(0.0008f, 0.0008f, 0.003f);

		// ── Layer 2: abyss below the detector ─────────────────────────────
		// UE5 stores second-layer fog in a SecondFogData struct (FExponentialHeightFogData);
		// the struct only carries Density / HeightFalloff / HeightOffset, and the layer
		// shares the component's FogInscatteringColor — there is no second-layer color.
		FC->SecondFogData.FogDensity       = 0.06f;   // thick lower void
		FC->SecondFogData.FogHeightFalloff = 0.5f;    // falls off with altitude
		FC->SecondFogData.FogHeightOffset  = -500.f;  // 500 cm below origin
	}
}
