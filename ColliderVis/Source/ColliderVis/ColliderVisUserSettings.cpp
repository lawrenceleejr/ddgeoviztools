// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisUserSettings.h"
#include "HAL/IConsoleManager.h"
#include "Engine/Engine.h"

UColliderVisUserSettings::UColliderVisUserSettings()
{
}

UColliderVisUserSettings* UColliderVisUserSettings::Get()
{
	// GEngine->GetGameUserSettings() returns the singleton; it will be an instance of this
	// subclass when GameUserSettingsClassName is configured in DefaultEngine.ini.
	return GEngine ? Cast<UColliderVisUserSettings>(GEngine->GetGameUserSettings()) : nullptr;
}

void UColliderVisUserSettings::SetCVarFloat(const TCHAR* Name, float Value)
{
	if (IConsoleVariable* CVar = IConsoleManager::Get().FindConsoleVariable(Name))
	{
		CVar->Set(Value, ECVF_SetByGameSetting);
	}
}

void UColliderVisUserSettings::SetCVarInt(const TCHAR* Name, int32 Value)
{
	if (IConsoleVariable* CVar = IConsoleManager::Get().FindConsoleVariable(Name))
	{
		CVar->Set(Value, ECVF_SetByGameSetting);
	}
}

void UColliderVisUserSettings::SetToDefaults()
{
	Super::SetToDefaults();

	LookSensitivity     = 0.15f;
	QualityPreset       = 2;   // High — Mac-friendly realtime default; menu scales up/down
	bLumenReflections   = true;
	bVolumetricFog      = true;
	bMotionBlur         = true;
	bBloom              = true;
	bDepthOfField       = true;
	bFilmGrain          = true;
	bScreenSpaceShadows = true;
	bNanite             = true;

	// Apply the Mac-friendly default scalability so a fresh install runs well out of
	// the box; the options menu lets the player scale up (to Cinematic) or down.
	SetOverallScalabilityLevel(QualityPreset);
}

void UColliderVisUserSettings::ApplySettings(bool bCheckForCommandLineOverrides)
{
	Super::ApplySettings(bCheckForCommandLineOverrides);
	ApplyColliderVisSettings();
}

void UColliderVisUserSettings::ApplyColliderVisSettings()
{
	// Re-push every stored feature flag to its CVar. Setters call into the same paths,
	// but this is the single entry point used after LoadSettings() at boot.
	SetLumenReflectionsEnabled(bLumenReflections);
	SetVolumetricFogEnabled(bVolumetricFog);
	SetMotionBlurEnabled(bMotionBlur);
	SetBloomEnabled(bBloom);
	SetDepthOfFieldEnabled(bDepthOfField);
	SetFilmGrainEnabled(bFilmGrain);
	SetScreenSpaceShadowsEnabled(bScreenSpaceShadows);
	SetNaniteEnabled(bNanite);
}

// ---- Mouse sensitivity ----

void UColliderVisUserSettings::SetLookSensitivity(float V)
{
	LookSensitivity = FMath::Clamp(V, 0.05f, 10.0f);
	SaveSettings();
	// NOTE: the live character reads this via its own SetLookSensitivity(); the UMG panel
	// is expected to push the value to the active AColliderVisCharacter (see CHANGELOG).
}

// ---- Master quality preset ----

void UColliderVisUserSettings::SetQualityPreset(int32 Preset)
{
	QualityPreset = FMath::Clamp(Preset, 0, 4);

	// Drive the engine scalability groups (ViewDistance, ShadowQuality, GlobalIllumination,
	// Reflections, PostProcess, Textures, Effects, Foliage, Shading) all to this level.
	SetOverallScalabilityLevel(QualityPreset);

	// Resolution settings need an explicit apply; ApplyResolutionSettings is the lighter call
	// that doesn't re-run the full ApplySettings (avoids recursing through ApplySettings here).
	ApplyResolutionSettings(false);

	SaveSettings();
}

// ---- Individual feature toggles ----
//
// CVar choices:
//   Lumen reflections      -> r.Lumen.Reflections.Allow (1/0)
//   Volumetric fog/god rays-> r.VolumetricFog (1/0)
//   Motion blur            -> r.MotionBlur.Amount (1.0/0.0 scale on the PP amount)
//   Bloom                  -> r.BloomQuality (5 default / 0 off)
//   Depth of field         -> r.DepthOfFieldQuality (2 default / 0 off)
//   Film grain             -> r.FilmGrain (1/0)
//   Screen-space shadows   -> r.Shadow.Virtual.Enable (1/0) + r.ContactShadows (1/0)
//   Nanite                 -> r.Nanite (1/0)

void UColliderVisUserSettings::SetLumenReflectionsEnabled(bool bEnabled)
{
	bLumenReflections = bEnabled;
	SetCVarInt(TEXT("r.Lumen.Reflections.Allow"), bEnabled ? 1 : 0);
	SaveSettings();
}

void UColliderVisUserSettings::SetVolumetricFogEnabled(bool bEnabled)
{
	bVolumetricFog = bEnabled;
	SetCVarInt(TEXT("r.VolumetricFog"), bEnabled ? 1 : 0);
	SaveSettings();
}

void UColliderVisUserSettings::SetMotionBlurEnabled(bool bEnabled)
{
	bMotionBlur = bEnabled;
	// 1.0 keeps the per-volume PP amount; 0.0 fully disables regardless of PP settings.
	SetCVarFloat(TEXT("r.MotionBlur.Amount"), bEnabled ? 1.0f : 0.0f);
	SaveSettings();
}

void UColliderVisUserSettings::SetBloomEnabled(bool bEnabled)
{
	bBloom = bEnabled;
	SetCVarInt(TEXT("r.BloomQuality"), bEnabled ? 5 : 0);
	SaveSettings();
}

void UColliderVisUserSettings::SetDepthOfFieldEnabled(bool bEnabled)
{
	bDepthOfField = bEnabled;
	SetCVarInt(TEXT("r.DepthOfFieldQuality"), bEnabled ? 2 : 0);
	SaveSettings();
}

void UColliderVisUserSettings::SetFilmGrainEnabled(bool bEnabled)
{
	bFilmGrain = bEnabled;
	SetCVarInt(TEXT("r.FilmGrain"), bEnabled ? 1 : 0);
	SaveSettings();
}

void UColliderVisUserSettings::SetScreenSpaceShadowsEnabled(bool bEnabled)
{
	bScreenSpaceShadows = bEnabled;
	// Virtual shadow maps + contact shadows together cover the moody contact shadowing.
	SetCVarInt(TEXT("r.Shadow.Virtual.Enable"), bEnabled ? 1 : 0);
	SetCVarInt(TEXT("r.ContactShadows"), bEnabled ? 1 : 0);
	SaveSettings();
}

void UColliderVisUserSettings::SetNaniteEnabled(bool bEnabled)
{
	bNanite = bEnabled;
	SetCVarInt(TEXT("r.Nanite"), bEnabled ? 1 : 0);
	SaveSettings();
}
