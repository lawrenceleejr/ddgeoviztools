#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "DetectorVisibilityConfig.h"
#include "DetectorVisibilityManager.generated.h"

/**
 * Placed in the level; scans all actors at BeginPlay and groups them by tag.
 * Provides visibility toggle API called from WBP_DetectorVisibility.
 */
UCLASS(BlueprintType)
class COLLIDERVIS_API ADetectorVisibilityManager : public AActor
{
	GENERATED_BODY()

public:
	ADetectorVisibilityManager();

	/** Assign DA_DetectorVisibility in the Details panel */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Config")
	UDetectorVisibilityConfig* Config;

	/** Show or hide all actors belonging to the named sub-detector */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Visibility")
	void SetSubDetectorVisible(FName Name, bool bVisible);

	/** Toggle current visibility of the named sub-detector */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Visibility")
	void ToggleSubDetector(FName Name);

	/** Show or hide all sub-detectors at once */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Visibility")
	void SetAllVisible(bool bVisible);

	/** Query current visibility state */
	UFUNCTION(BlueprintPure, Category = "ColliderVis|Visibility")
	bool IsSubDetectorVisible(FName Name) const;

	/** Re-scan the level for tagged actors (call after importing new static meshes) */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Visibility")
	void RebuildActorCache();

protected:
	virtual void BeginPlay() override;

private:
	/** Populated on BeginPlay: SubDetectorName → TArray of matching actors */
	TMap<FName, TArray<AActor*>> SubDetectorActors;

	/** Tracks current visibility per sub-detector */
	TMap<FName, bool> VisibilityState;

	/** Apply visibility to every component in an actor */
	static void ApplyVisibility(AActor* Actor, bool bVisible);
};
