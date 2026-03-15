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

/**
 * Third-person playable character for Explore mode.
 * Uses Enhanced Input System exclusively — no legacy bindings.
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

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* SwitchModeAction;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* ToggleDetectorMenuAction;

	// ---- Input Handlers ----

	void Move(const FInputActionValue& Value);
	void Look(const FInputActionValue& Value);
	void OnNextEvent(const FInputActionValue& Value);
	void OnOpenMenu(const FInputActionValue& Value);
	void OnSwitchMode(const FInputActionValue& Value);
	void OnToggleDetectorMenu(const FInputActionValue& Value);

	/** Subtle landing camera shake */
	UPROPERTY(EditAnywhere, Category = "Camera", meta = (AllowPrivateAccess = "true"))
	TSubclassOf<class UCameraShakeBase> LandingShake;

	/** Loads Input assets by /Game/Input/ path if not already set via BP */
	void DiscoverInputAssets();
};
