// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "InputActionValue.h"
#include "ColliderVisVRPawn.generated.h"

class UCameraComponent;
class UMotionControllerComponent;
class UInputMappingContext;
class UInputAction;
class AEventDisplayManager;

/**
 * VR pawn for Meta Quest 3 — works both tethered (PCVR via OpenXR) and
 * as a standalone Android binary loaded onto the headset.
 *
 * First-person mode  — HMD tracks head rotation naturally.
 *   Left stick        → smooth locomotion in camera-forward direction.
 *   Right stick X     → smooth yaw turn (for when physical rotation isn't practical).
 *   Right grip/button → toggle orbit mode.
 *
 * Orbit mode         — pawn is repositioned on a sphere around the detector origin;
 *                      the player sees the detector in front of them.
 *   Right stick       → rotate orbit (yaw + pitch).
 *   Right trigger held→ zoom orbit radius inward for detail inspection.
 *   Right grip/button → toggle back to first-person.
 *
 * IMC: create IMC_VR in Content/Input/, map Quest 3 OpenXR axes/buttons to the
 * same IA_ assets already used by the desktop character (IA_Move, IA_Look /
 * repurposed as IA_Turn here, IA_SwitchMode, IA_Zoom, IA_NextEvent).
 */
UCLASS(Blueprintable)
class COLLIDERVIS_API AColliderVisVRPawn : public APawn
{
	GENERATED_BODY()

public:
	AColliderVisVRPawn();

	UPROPERTY(BlueprintReadWrite, Category = "ColliderVis")
	AEventDisplayManager* EventDisplayManager;

	/** Smooth locomotion speed in first-person (cm/s). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Locomotion")
	float MoveSpeed = 300.f;

	/** Smooth yaw turn speed in first-person (degrees/s per stick unit). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Locomotion")
	float TurnSpeed = 90.f;

	/** Orbit rotation speed (degrees/s per stick unit). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Orbit")
	float OrbitRotateSpeed = 60.f;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaTime) override;
	virtual void SetupPlayerInputComponent(UInputComponent* PlayerInputComponent) override;

private:
	// ---- VR Components ----

	/** Tracking-space origin — all VR components attach here. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	USceneComponent* VROrigin;

	/** Camera follows the HMD automatically when OpenXR is active. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	UCameraComponent* VRCamera;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	UMotionControllerComponent* LeftHand;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	UMotionControllerComponent* RightHand;

	// ---- Input ----

	/** VR-specific mapping context (IMC_VR) — maps controller axes/buttons. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputMappingContext* VRMappingContext;

	/** Left stick — locomotion in first-person mode (Vector2D). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* MoveAction;

	/**
	 * Right stick — smooth yaw turn in first-person; orbit rotate in orbit mode.
	 * Reuses IA_Look so no new asset is required.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* TurnAction;

	/** Controller button (e.g. right grip) — toggles first-person ↔ orbit. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* SwitchModeAction;

	/** Right trigger held — zooms orbit radius toward origin. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* ZoomAction;

	/** Face button (e.g. right A) — advance to next collision event. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* NextEventAction;

	/** Left menu / B button — open/close the options menu. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* OpenMenuAction;

	// ---- Orbit State ----

	bool  bOrbitMode  = false;
	float OrbitYaw    = -30.f;
	float OrbitPitch  = -20.f;
	float OrbitRadius = 1200.f;   // current radius, interpolated by Tick
	bool  bZoomHeld   = false;

	static constexpr float DefaultOrbitRadius = 1200.f;
	static constexpr float ZoomedOrbitRadius  = 250.f;

	// ---- Handlers ----

	void OnMove(const FInputActionValue& Value);
	void OnTurn(const FInputActionValue& Value);
	void OnSwitchMode(const FInputActionValue& Value);
	void OnZoomStarted(const FInputActionValue& Value);
	void OnZoomCompleted(const FInputActionValue& Value);
	void OnNextEvent(const FInputActionValue& Value);
	void OnOpenMenu(const FInputActionValue& Value);

	/** Move the pawn onto the orbit sphere and face it toward the origin. */
	void UpdateOrbitPosition();

	void DiscoverInputAssets();
};
