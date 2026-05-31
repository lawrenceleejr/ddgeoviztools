// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "InputActionValue.h"
#include "ColliderVisCharacter.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UInputMappingContext;
class UInputAction;
class AEventDisplayManager;
class AOrbitCameraActor;
class ADetectorVisibilityManager;

/**
 * Third-person playable character for Explore mode.
 * Uses Enhanced Input System exclusively — no legacy bindings.
 *
 * Tab         — toggles between third-person follow camera and orbit camera
 *               (fixed pivot at world origin / detector centre, mouse rotates).
 * Mouse click — hold either mouse button to dynamically zoom the camera in
 *               (spring arm pulls in + FOV narrows) so the user can see detail.
 */
UCLASS(BlueprintType, Blueprintable)
class COLLIDERVIS_API AColliderVisCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	AColliderVisCharacter();

	/** Cached reference to the level's EventDisplayManager */
	UPROPERTY(BlueprintReadWrite, Category = "ColliderVis")
	AEventDisplayManager* EventDisplayManager;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaTime) override;
	virtual void SetupPlayerInputComponent(UInputComponent* PlayerInputComponent) override;
	// In UE 5.x the C++ virtual hook is `Landed`; `OnLanded` is the
	// Blueprint display name only.  Older versions of this project
	// used `OnLanded`, which never actually overrode anything (silent
	// no-op on Blender — error on UE 5.7).
	virtual void Landed(const FHitResult& Hit) override;

private:
	// ---- Components ----

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	USpringArmComponent* CameraBoom;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta = (AllowPrivateAccess = "true"))
	UCameraComponent* FollowCamera;

	// ---- Input Asset References (discovered at runtime by path) ----

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputMappingContext* DefaultMappingContext;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* MoveAction;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* LookAction;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* JumpAction;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* NextEventAction;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* OpenMenuAction;

	/** Tab — toggles between third-person and orbit camera */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* SwitchModeAction;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* ToggleDetectorMenuAction;

	/** Mouse click (held) — zoom in while in third-person mode */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* ZoomAction;

	/**
	 * Single Axis1D action bound to keys 1–9 via scalar modifiers in IMC_Default.
	 * The float value encodes which slot was pressed (1.0 = key 1 … 9.0 = key 9).
	 * Each DA_DetectorVisibility entry's HotkeySlot field selects which key maps to it.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* DetectorKeyAction;

	// ---- Orbit Camera ----

	/** Spawned once in BeginPlay; lives at the world origin (detector centre). */
	UPROPERTY()
	AOrbitCameraActor* OrbitCam;

	/** Found in BeginPlay; drives sub-detector visibility via number keys. */
	UPROPERTY()
	ADetectorVisibilityManager* VisibilityManager;

	bool bOrbitMode = false;

	// ---- Third-person Zoom (mouse click) ----
	// Holding a mouse button pulls the spring arm in AND narrows the camera FOV,
	// so the user can lean in to inspect detector / event detail.  Tick() smoothly
	// interpolates both back and forth.

	bool  bZoomHeld        = false;
	float DefaultArmLength = 400.f;
	float ZoomedArmLength  = 150.f;
	float DefaultFOV       = 90.f;
	float ZoomedFOV        = 40.f;

	// ---- Orbit RMB Zoom ----

	float DefaultOrbitRadius = 1200.f;   // matches AOrbitCameraActor constructor
	float ZoomedOrbitRadius  = 250.f;    // close enough to inspect detector detail

	// ---- Input Handlers ----

	void Move(const FInputActionValue& Value);
	void Look(const FInputActionValue& Value);
	void OnNextEvent(const FInputActionValue& Value);
	void OnOpenMenu(const FInputActionValue& Value);
	void OnSwitchMode(const FInputActionValue& Value);
	void OnToggleDetectorMenu(const FInputActionValue& Value);
	void OnZoomStarted(const FInputActionValue& Value);
	void OnZoomCompleted(const FInputActionValue& Value);
	void OnDetectorKey(const FInputActionValue& Value);

	/** Subtle landing camera shake */
	UPROPERTY(EditAnywhere, Category = "Camera", meta = (AllowPrivateAccess = "true"))
	TSubclassOf<class UCameraShakeBase> LandingShake;

	/** Loads Input assets by /Game/Input/ path if not already set via BP */
	void DiscoverInputAssets();
};
