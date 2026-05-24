// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "OrbitCameraActor.generated.h"

class USpringArmComponent;
class UCameraComponent;

/**
 * A camera that orbits a fixed world-space pivot (defaults to the origin,
 * i.e. the detector centre).  Mouse look rotates the orbit; no tick needed.
 *
 * Activation: AColliderVisCharacter calls PC->SetViewTargetWithBlend(OrbitCam)
 * on Tab, and routes its Look input here while in orbit mode.
 */
UCLASS(Blueprintable)
class COLLIDERVIS_API AOrbitCameraActor : public AActor
{
	GENERATED_BODY()

public:
	AOrbitCameraActor();

	/**
	 * Rotate the orbital position by the given yaw and pitch deltas (degrees).
	 * Pitch is clamped to ±85° to prevent gimbal-lock at the poles.
	 */
	void AddOrbitInput(float DeltaYaw, float DeltaPitch);

	/** Adjust the orbit radius.  Positive Delta = zoom in, negative = zoom out. */
	void AddZoom(float Delta);

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Orbit")
	TObjectPtr<USpringArmComponent> Arm;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Orbit")
	TObjectPtr<UCameraComponent> Cam;

	/** Minimum orbit radius (cm). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Orbit")
	float MinRadius = 200.f;

	/** Maximum orbit radius (cm). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Orbit")
	float MaxRadius = 6000.f;

private:
	float CurrentYaw   = -30.f;
	float CurrentPitch = -25.f;   // start slightly above the equatorial plane
};
