// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameUserSettings.h"
#include "ColliderVisUserSettings.generated.h"

/**
 * Project-specific persisted user settings for ColliderVis.
 *
 * Subclasses UGameUserSettings so all the stock machinery (GameUserSettings.ini
 * persistence, scalability groups, resolution) is inherited, and adds:
 *   - a runtime mouse-look sensitivity (mirrors AColliderVisCharacter::LookSensitivity),
 *   - per-feature toggles for the expensive rendering features in the cinematic look,
 *   - a 0..4 master quality preset that drives the engine scalability groups.
 *
 * Every setter is BlueprintCallable so the UMG settings panel can bind directly to it,
 * applies its effect immediately via console variables / scalability, and the values are
 * persisted through SaveSettings() (stock UGameUserSettings ini serialization).
 *
 * To make the engine instantiate THIS class instead of stock UGameUserSettings, set in
 * DefaultEngine.ini:
 *   [/Script/Engine.Engine]
 *   GameUserSettingsClassName=/Script/ColliderVis.ColliderVisUserSettings
 * (orchestrator config step — see CHANGELOG).
 */
UCLASS(BlueprintType, Config = GameUserSettings)
class COLLIDERVIS_API UColliderVisUserSettings : public UGameUserSettings
{
	GENERATED_BODY()

public:
	UColliderVisUserSettings();

	/** Convenience accessor — returns the active settings object as this subclass. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	static UColliderVisUserSettings* Get();

	// ---- UGameUserSettings overrides ----
	virtual void SetToDefaults() override;
	/** Re-applies every ColliderVis setting via CVars, then chains to the base apply. */
	virtual void ApplySettings(bool bCheckForCommandLineOverrides) override;

	/** Pushes every stored ColliderVis CVar value to the renderer (call after load/apply). */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void ApplyColliderVisSettings();

	// ---- Mouse sensitivity ----

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetLookSensitivity(float V);

	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	float GetLookSensitivity() const { return LookSensitivity; }

	// ---- Master quality preset (0=Low 1=Medium 2=High 3=Epic 4=Cinematic) ----

	/** Maps the preset to the engine scalability groups via SetOverallScalabilityLevel. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetQualityPreset(int32 Preset);

	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	int32 GetQualityPreset() const { return QualityPreset; }

	// ---- Individual expensive-feature toggles ----
	// Each setter stores the flag, applies the matching CVar immediately, and persists.

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetLumenReflectionsEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetLumenReflectionsEnabled() const { return bLumenReflections; }

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetVolumetricFogEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetVolumetricFogEnabled() const { return bVolumetricFog; }

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetMotionBlurEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetMotionBlurEnabled() const { return bMotionBlur; }

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetBloomEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetBloomEnabled() const { return bBloom; }

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetDepthOfFieldEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetDepthOfFieldEnabled() const { return bDepthOfField; }

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetFilmGrainEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetFilmGrainEnabled() const { return bFilmGrain; }

	/** Screen-space / virtual-shadow toggle (the moody contact shadows in the look spec). */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetScreenSpaceShadowsEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetScreenSpaceShadowsEnabled() const { return bScreenSpaceShadows; }

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Settings")
	void SetNaniteEnabled(bool bEnabled);
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Settings")
	bool GetNaniteEnabled() const { return bNanite; }

protected:
	// ---- Persisted values (serialized to GameUserSettings.ini) ----

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	float LookSensitivity = 0.15f;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	int32 QualityPreset = 2;   // High by default (Mac-friendly realtime; menu scales 0..4)

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bLumenReflections = true;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bVolumetricFog = true;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bMotionBlur = true;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bBloom = true;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bDepthOfField = true;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bFilmGrain = true;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bScreenSpaceShadows = true;

	UPROPERTY(Config, BlueprintReadOnly, Category = "ColliderVis|Settings")
	bool bNanite = true;

private:
	/** Sets a console variable by name to a float value at game priority. */
	static void SetCVarFloat(const TCHAR* Name, float Value);
	/** Sets a console variable by name to an int value at game priority. */
	static void SetCVarInt(const TCHAR* Name, int32 Value);
};
