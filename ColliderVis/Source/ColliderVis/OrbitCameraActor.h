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

	/** Keep DoF focal distance locked to the camera-to-origin distance (arm length). */
	void UpdateFocusDistance();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Orbit")
	TObjectPtr<USpringArmComponent> Arm;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Orbit")
	TObjectPtr<UCameraComponent> Cam;

	/** Minimum orbit radius (cm). Very small so scroll-zoom can get right up to the IP. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Orbit")
	float MinRadius = 30.f;

	/** Maximum orbit radius (cm). Clamped to just inside the environment sphere
	 *  (radius ~4500) so the player can't zoom out past the dome. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Orbit")
	float MaxRadius = 4400.f;

private:
	// Start looking into the detector's phi cutaway (open wedge faces −Y), then
	// offset 45° to the side and 30° up for a cinematic 3/4 hero angle on the
	// revealed interior.
	float CurrentYaw   = 165.f;   // 90° (cutaway) + 45° side + 30° further to the right
	float CurrentPitch = -30.f;   // 30° elevated, looking down into the opening
};
