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
class USoundBase;

/**
 * Third-person playable character for Explore mode.
 * Uses Enhanced Input System exclusively — no legacy bindings.
 *
 * Tab         — toggles between third-person follow camera and orbit camera
 *               (fixed pivot at world origin / detector centre, mouse rotates).
 * RMB (held)  — dynamically zoom the camera in (spring arm pulls in + FOV
 *               narrows) so the user can see detail.
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

	// ---- Mouse look sensitivity (runtime-settable) ----

	/**
	 * Multiplier applied on top of the base look scale. 1.0 = default feel.
	 * Driven by the settings menu mouse-sensitivity slider via SetLookSensitivity().
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Input")
	float LookSensitivity = 0.15f;

	/** Sets the runtime look sensitivity (called from the UMG settings panel). */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Input")
	void SetLookSensitivity(float V);

	// ---- Movement: sprint + fly ----

	/** Ground walk speed (cm/s). Matches the constructor's MaxWalkSpeed default. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Movement")
	float WalkSpeed = 600.f;

	/** Ground speed while holding sprint (~2x walk). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Movement")
	float SprintSpeed = 1200.f;

	/** Flight speed while NOT sprinting. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Movement")
	float FlySpeed = 1500.f;

	/** Flight speed while holding sprint. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Movement")
	float FlySprintSpeed = 3000.f;

	/** True while in flying movement mode (read by AnimBP / BP). */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis|Movement")
	bool bFlying = false;

	// ---- Idle / bored state ----

	/** Seconds of no input before the character is considered "bored". */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Idle")
	float IdleThreshold = 15.0f;

	/** True while the character has been idle past IdleThreshold. Read by the AnimBP. */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis|Idle")
	bool bIsBored = false;

	/** Fired once when the character first becomes bored. AnimBP/BP hooks the bored idle here. */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Idle")
	void OnBecmeBored();

	/** Fired once when any input pulls the character out of the bored state. */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Idle")
	void OnExitBored();

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

	/** RMB (held) — zoom in while in third-person mode */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* ZoomAction;

	/** LMB — trigger the next animated event on the EventDisplayManager */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* PlayEventAction;

	/** Left Shift (held) — sprint: boosts ground/fly speed while down */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* SprintAction;

	/** F — toggle flying / walking */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* FlyAction;

	/** Q (held) — descend while flying (moves DOWN along world Z). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* FlyDownAction;

	/** E (held) — ascend while flying (moves UP along world Z). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* FlyUpAction;

	/** Mouse wheel (Axis1D) — dolly the orbit camera radius while in orbit mode */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Input", meta = (AllowPrivateAccess = "true"))
	UInputAction* ScrollAction;

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

	// ---- Idle / bored timer ----
	// Seconds since the last move/look/zoom/jump/etc. input.  Ticked up every frame
	// and reset to 0 by NoteInput() inside every input handler.  When it crosses
	// IdleThreshold we flip bIsBored and fire OnBecmeBored() once.
	float TimeSinceLastInput = 0.f;

	// Procedural "bored" look-around (drives a slow yaw sway while bIsBored).
	float BoredElapsed = 0.f;
	/** Peak yaw rate (deg/s) of the bored look-around sway. */
	UPROPERTY(EditAnywhere, Category = "ColliderVis|Idle")
	float BoredLookSpeed = 9.0f;
	/** Frequency (rad/s) of the bored look-around sway. */
	UPROPERTY(EditAnywhere, Category = "ColliderVis|Idle")
	float BoredLookFreq = 0.55f;

	/** Base mouse-look scale; multiplied by LookSensitivity in Look(). */
	static constexpr float BaseLookScale = 2.0f;

	/** Resets the idle timer and clears the bored state (firing OnExitBored once). */
	void NoteInput();

	// ---- Third-person Zoom (RMB) ----
	// Holding RMB pulls the spring arm in AND narrows the camera FOV, so the user
	// can lean in to inspect detector / event detail.  Tick() smoothly interpolates
	// both back and forth.

	bool  bZoomHeld        = false;
	float DefaultArmLength = 400.f;
	float ZoomedArmLength  = 150.f;
	float DefaultFOV       = 100.f;  // wider follow-camera FOV (was 90)
	float ZoomedFOV        = 40.f;

	// ---- Over-the-shoulder aim offset (RMB, third-person) ----
	// While zoomed, the spring-arm socket offset slides to the side so the camera
	// looks over the character's shoulder (and the body mesh is hidden for a clean
	// view).  Tick() interpolates these toward/away from the aimed pose.
	FVector DefaultSocketOffset = FVector(0.f,  0.f,  0.f);
	FVector ZoomedSocketOffset  = FVector(0.f, 60.f, 20.f);

	/** Tracks whether the mesh is currently hidden by the zoom (so we only toggle on change). */
	bool bMeshHiddenByZoom = false;

	// ---- Orbit-mode zoom ----
	// Two independent controls in orbit mode:
	//  * Mouse wheel persistently dollies the orbit RADIUS via OrbitCam->AddZoom().
	//  * RMB (held) is a TEMPORARY FOV punch-in on top of the scroll-set view: it
	//    narrows the orbit camera's FieldOfView and reverts on release.  RMB never
	//    touches the radius — scroll owns the radius, RMB owns the temporary FOV.

	/** Per-wheel-notch scale applied to OrbitCam->AddZoom() (which adds its own 80x). */
	float OrbitScrollScale = 1.0f;

	/** Orbit camera resting FOV (UCameraComponent default). */
	float OrbitDefaultFOV  = 90.f;

	/** Orbit camera FOV while RMB is held — a temporary punch-in. */
	float OrbitZoomedFOV   = 45.f;

	// ---- Input Handlers ----

	void Move(const FInputActionValue& Value);
	void Look(const FInputActionValue& Value);
	/** Wraps ACharacter::Jump so jumping also counts as input for the idle timer. */
	void OnJump(const FInputActionValue& Value);
	void OnNextEvent(const FInputActionValue& Value);
	void OnOpenMenu(const FInputActionValue& Value);
	void OnSwitchMode(const FInputActionValue& Value);
	void OnToggleDetectorMenu(const FInputActionValue& Value);
	void OnZoomStarted(const FInputActionValue& Value);
	void OnZoomCompleted(const FInputActionValue& Value);
	/** Mouse wheel — dolly the orbit camera radius (orbit mode only). */
	void OnScroll(const FInputActionValue& Value);
	void OnPlayEvent(const FInputActionValue& Value);
	void OnDetectorKey(const FInputActionValue& Value);
	/** Left Shift pressed/released — toggles sprint on the active movement mode. */
	void OnSprintStarted(const FInputActionValue& Value);
	void OnSprintCompleted(const FInputActionValue& Value);
	/** F — toggle between walking and flying. */
	void OnFlyToggle(const FInputActionValue& Value);
	/** Q (held) — descend along world -Z while flying (no-op otherwise). */
	void OnFlyDown(const FInputActionValue& Value);
	/** E (held) — ascend along world +Z while flying (no-op otherwise). */
	void OnFlyUp(const FInputActionValue& Value);

	/** Number keys 1-4 — toggle show/hide of detector phi-quadrant 1-4 via MPC_Cutaway. */
	void OnCutawayQuadrant1();
	void OnCutawayQuadrant2();
	void OnCutawayQuadrant3();
	void OnCutawayQuadrant4();
	/** Flips the MPC_Cutaway scalar "Q<Quadrant>" between 0 (show) and 1 (hide). */
	void ToggleCutawayQuadrant(int32 Quadrant);

	/** Runtime-created Boolean input actions for the four cutaway-quadrant number keys
	 *  (1-4). Created in code and mapped in the C++ IMC, since the project drives all
	 *  input through Enhanced Input — raw BindKey does not fire. */
	UPROPERTY()
	TArray<TObjectPtr<UInputAction>> CutawayActions;

	// ── Floor elevator (C key) ──────────────────────────────────────────────────
	/** C — toggle the walkable floor between the detector bottom and middle. */
	void OnFloorElevatorToggle();
	UPROPERTY() TObjectPtr<UInputAction> FloorElevatorAction;

	// ── Respawn (Z key) ─────────────────────────────────────────────────────────
	/** Z — teleport the player back to the level PlayerStart. */
	void OnRespawn();
	UPROPERTY() TObjectPtr<UInputAction> RespawnAction;
	/** The Movable walkable floor (tagged "ElevatorFloor"); rides between two heights. */
	UPROPERTY() TObjectPtr<AActor> ElevatorFloor;
	float FloorDownZ      = -600.f;  // actor Z so the slab top sits at the detector bottom (~-590)
	float FloorUpZ        = -10.f;   // actor Z so the slab top sits at the detector middle (~0)
	float FloorAlpha      = 0.f;     // 0 = down, 1 = up (linear travel param)
	float FloorTarget     = 0.f;
	float FloorTravelTime = 1.1f;    // seconds end-to-end — fast elevator
	bool  bFloorAnimating = false;

	/** Glowing call-pad (tagged "ElevatorPad", attached to the elevator floor): stepping
	 *  onto its 2 m × 2 m footprint toggles the elevator, same as the C key. */
	UPROPERTY() TObjectPtr<AActor> ElevatorPad;
	float PadHalfExtent   = 100.f;   // cm — half of the 2 m square footprint
	bool  bOnPad          = false;   // edge-detect so we toggle once per step-on
	float PadZOffset      = 615.f;   // beam pivot Z above the floor actor Z (base just above slab; = slab-half + gap + beam-half-height for the 12 m beam)
	/** Soft reverb-y chime played when the player steps onto the call-pad. */
	UPROPERTY() TObjectPtr<USoundBase> PadSound;

	/** True while Left Shift is held; applies the current sprint speed. */
	bool bSprinting = false;

	/** Re-applies MaxWalkSpeed / MaxFlySpeed from the current sprint + fly state. */
	void ApplyMovementSpeed();

	/** Subtle landing camera shake */
	UPROPERTY(EditAnywhere, Category = "Camera", meta = (AllowPrivateAccess = "true"))
	TSubclassOf<class UCameraShakeBase> LandingShake;

	/** Loads Input assets by /Game/Input/ path if not already set via BP */
	void DiscoverInputAssets();
};
