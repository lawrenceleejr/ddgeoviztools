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

/**
 * Third-person playable character for Explore mode.
 * Uses Enhanced Input System exclusively — no legacy bindings.
 *
 * Tab         — toggles between third-person follow camera and orbit camera
 *               (fixed pivot at world origin / detector centre, mouse rotates).
 * RMB (held)  — zooms the third-person spring arm in toward the character.
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
	virtual void OnLanded(const FHitResult& Hit) override;

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

	/** RMB — zoom in while in third-person mode */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* ZoomAction;

	// ---- Orbit Camera ----

	/** Spawned once in BeginPlay; lives at the world origin (detector centre). */
	UPROPERTY()
	AOrbitCameraActor* OrbitCam;

	bool bOrbitMode = false;

	// ---- Third-person RMB Zoom ----

	bool  bZoomHeld        = false;
	float DefaultArmLength = 400.f;
	float ZoomedArmLength  = 150.f;

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

	/** Subtle landing camera shake */
	UPROPERTY(EditAnywhere, Category = "Camera", meta = (AllowPrivateAccess = "true"))
	TSubclassOf<class UCameraShakeBase> LandingShake;

	/** Loads Input assets by /Game/Input/ path if not already set via BP */
	void DiscoverInputAssets();
};
