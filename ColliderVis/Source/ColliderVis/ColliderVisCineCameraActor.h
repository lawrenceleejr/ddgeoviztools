#pragma once

#include "CoreMinimal.h"
#include "Camera/CameraActor.h"
#include "ColliderVisCineCameraActor.generated.h"

class AEventDisplayManager;

/**
 * Cinematic camera for Viz/Movie mode.
 * Configures a 50mm full-frame equivalent FOV with f/1.8 shallow DoF via the
 * camera component's PostProcessSettings (no CinematicCamera plugin required).
 * Auto-focuses on the event centroid each tick.
 */
UCLASS(BlueprintType, Blueprintable)
class COLLIDERVIS_API AColliderVisCineCameraActor : public ACameraActor
{
	GENERATED_BODY()

public:
	AColliderVisCineCameraActor();

	/** Reference to level's EventDisplayManager for auto-focus targeting */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis")
	AEventDisplayManager* EventDisplayManager;

	/**
	 * Smoothly animate focus distance toward the current event centroid.
	 * Called automatically each tick; can also be driven from Blueprint.
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Camera")
	void UpdateFocusToCentroid(float DeltaTime, float InterpSpeed = 3.f);

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaTime) override;
};
