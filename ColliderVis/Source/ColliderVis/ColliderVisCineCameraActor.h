#pragma once

#include "CoreMinimal.h"
#include "CineCameraActor.h"
#include "ColliderVisCineCameraActor.generated.h"

class AEventDisplayManager;

/**
 * Cinematic camera for Viz/Movie mode.
 * Pre-configured with anamorphic lens presets and auto-focus on the event centroid.
 */
UCLASS(BlueprintType, Blueprintable)
class COLLIDERVIS_API AColliderVisCineCameraActor : public ACineCameraActor
{
	GENERATED_BODY()

public:
	AColliderVisCineCameraActor();

	/** Reference to level's EventDisplayManager for auto-focus targeting */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis")
	AEventDisplayManager* EventDisplayManager;

	/**
	 * Smoothly animate focus distance toward the current event centroid.
	 * Call this on a tick or after LoadEvent().
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Camera")
	void UpdateFocusToCentroid(float DeltaTime, float InterpSpeed = 3.f);

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaTime) override;
};
