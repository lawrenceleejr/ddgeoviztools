// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Engine/GameInstance.h"
#include "ColliderVisGameInstance.generated.h"

class USplashWidget;

/**
 * GameInstance for ColliderVis. Persists across level loads and owns the
 * launch boot flow: it shows the splash/title screen once at startup before
 * the detector level is entered.
 *
 * HOW TO USE (orchestrator):
 *   - Set this as the project's GameInstance class in
 *     Project Settings → Project → Maps & Modes → Game Instance Class.
 *   - Set SplashWidgetClass (or place WBP_Splash at /Game/UI/WBP_Splash for
 *     auto-discovery). Assign WBP_Splash to a child Blueprint of this class if
 *     you prefer configuring it in the editor.
 *   - Set the project startup map to a lightweight splash/loading map (or to
 *     ColliderVisMain itself — the splash overlays whatever map loads first).
 *
 * FLOW:
 *   Init()/first map load → ShowSplash() creates USplashWidget → splash
 *   auto-/input-dismisses → SplashWidget opens /Game/Maps/ColliderVisMain.
 *   The bSplashShown guard ensures the splash never appears twice.
 */
UCLASS(BlueprintType, Blueprintable)
class COLLIDERVIS_API UColliderVisGameInstance : public UGameInstance
{
	GENERATED_BODY()

public:
	/**
	 * Splash widget class to instantiate. Set to WBP_Splash, or leave null and
	 * place WBP_Splash at /Game/UI/WBP_Splash for auto-discovery.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Boot")
	TSubclassOf<USplashWidget> SplashWidgetClass;

	/**
	 * Name of the map that the splash itself lives on / launches from. When the
	 * current map's name matches this, ShowSplash() will run on map load.
	 * Empty = show on the very first loaded map regardless of name.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Boot")
	FName SplashMapName = NAME_None;

	/** Creates and shows the splash widget once. No-op if already shown. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Boot")
	void ShowSplash();

	virtual void Init() override;

protected:
	/** Bound to FCoreUObjectDelegates post-load so we have a valid world/PC. */
	void HandlePostLoadMap(UWorld* LoadedWorld);

private:
	/** Guard so the splash is only ever shown once per process. */
	bool bSplashShown = false;

	/** Resolve SplashWidgetClass, falling back to /Game/UI/WBP_Splash. */
	TSubclassOf<USplashWidget> ResolveSplashWidgetClass();
};
