// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisCharacter.h"
#include "OrbitCameraActor.h"
#include "EventDisplayManager.h"
#include "DetectorVisibilityManager.h"
#include "DetectorVisibilityConfig.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputMappingContext.h"
#include "InputAction.h"
#include "InputActionValue.h"
#include "InputModifiers.h"
#include "InputTriggers.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundBase.h"
#include "GameFramework/PlayerStart.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"
#include "ColliderVisHUD.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Animation/AnimInstance.h"
#include "UObject/ConstructorHelpers.h"

AColliderVisCharacter::AColliderVisCharacter()
{
	PrimaryActorTick.bCanEverTick = true;   // needed for arm-length zoom interpolation

	// Spring Arm — cinematic lag for smooth follow
	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(RootComponent);
	CameraBoom->TargetArmLength          = DefaultArmLength;
	CameraBoom->bUsePawnControlRotation  = true;
	// Realistic camera motion: smooth position + rotation lag so the boom trails the
	// pawn naturally instead of snapping.  Rotation lag is kept brisk (10) so mouse-look
	// still feels responsive; a small max-distance keeps the camera from drifting far.
	CameraBoom->bEnableCameraLag         = true;
	CameraBoom->CameraLagSpeed           = 12.f;
	CameraBoom->CameraLagMaxDistance     = 50.f;   // clamp position trailing
	CameraBoom->bEnableCameraRotationLag = true;
	CameraBoom->CameraRotationLagSpeed   = 10.f;   // smooth but responsive mouse-look
	CameraBoom->SocketOffset             = DefaultSocketOffset;
	CameraBoom->bDoCollisionTest         = true;

	// Follow Camera
	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;
	FollowCamera->SetFieldOfView(DefaultFOV);

	// ── Example third-person model ──────────────────────────────────────────
	// Use the UE "Third Person" feature-pack Mannequin (Quinn) as the playable
	// avatar, if that content is present in the project
	// (/Game/Characters/Mannequins/...).  All lookups are guarded by .Succeeded()
	// so the character stays playable (just invisible) when the pack hasn't been
	// added yet — add it via "Add Feature or Content Pack → Third Person", then
	// recompile.  See UE5_SETUP.md / README_UE5_IMPORT.md.
	if (USkeletalMeshComponent* MeshComp = GetMesh())
	{
		// Standard mannequin offset: feet on the capsule base, facing +X.
		MeshComp->SetRelativeLocationAndRotation(
			FVector(0.f, 0.f, -89.f), FRotator(0.f, -90.f, 0.f));

		static ConstructorHelpers::FObjectFinder<USkeletalMesh> QuinnMesh(
			TEXT("/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple.SKM_Quinn_Simple"));
		if (QuinnMesh.Succeeded())
		{
			MeshComp->SetSkeletalMesh(QuinnMesh.Object);
		}

		// UE 5.7 ships the locomotion anim BP as ABP_Unarmed (SK_Mannequin skeleton — matches Quinn);
		// the older ABP_Quinn path no longer exists in the Third Person template.
		static ConstructorHelpers::FClassFinder<UAnimInstance> QuinnAnim(
			TEXT("/Game/Characters/Mannequins/Anims/Unarmed/ABP_Unarmed"));
		if (QuinnAnim.Succeeded())
		{
			MeshComp->SetAnimInstanceClass(QuinnAnim.Class);
		}
	}

	// Character movement defaults
	GetCharacterMovement()->bOrientRotationToMovement        = false;
	GetCharacterMovement()->RotationRate                     = FRotator(0.f, 720.f, 0.f);
	GetCharacterMovement()->JumpZVelocity                    = 700.f;
	GetCharacterMovement()->AirControl                       = 0.35f;
	GetCharacterMovement()->MaxWalkSpeed                     = 600.f;
	GetCharacterMovement()->MinAnalogWalkSpeed               = 20.f;
	GetCharacterMovement()->BrakingDecelerationWalking       = 2000.f;

	// Sprint/fly: WalkSpeed mirrors the MaxWalkSpeed default above so restoring on
	// shift-release returns the character to its baseline ground speed.  Flight speed
	// is seeded here too so the spline-style spectator fly feels smooth.
	WalkSpeed                                                = 600.f;
	GetCharacterMovement()->MaxFlySpeed                      = FlySpeed;
	GetCharacterMovement()->BrakingDecelerationFlying        = 2000.f;

	// Mouse/camera yaw drives the character's facing (over-the-shoulder): the body turns with the
	// camera. NOTE: yaw must be TRUE here — an earlier duplicate set it back to false and cancelled
	// the facing, so the character never rotated.
	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw   = true;
	bUseControllerRotationRoll  = false;
}

void AColliderVisCharacter::BeginPlay()
{
	Super::BeginPlay();

	// Find EventDisplayManager in level
	TArray<AActor*> Found;
	UGameplayStatics::GetAllActorsOfClass(GetWorld(), AEventDisplayManager::StaticClass(), Found);
	if (Found.Num() > 0)
	{
		EventDisplayManager = Cast<AEventDisplayManager>(Found[0]);
	}

	// Find DetectorVisibilityManager in level
	Found.Empty();
	UGameplayStatics::GetAllActorsOfClass(GetWorld(), ADetectorVisibilityManager::StaticClass(), Found);
	if (Found.Num() > 0)
	{
		VisibilityManager = Cast<ADetectorVisibilityManager>(Found[0]);
	}

	// Find the elevator floor (tagged "ElevatorFloor") and start it in the DOWN
	// position (slab top at the detector bottom). The C key rides it up to the middle.
	Found.Empty();
	UGameplayStatics::GetAllActorsWithTag(GetWorld(), FName("ElevatorFloor"), Found);
	if (Found.Num() > 0)
	{
		ElevatorFloor = Found[0];
		FloorAlpha = 0.f; FloorTarget = 0.f; bFloorAnimating = false;
		const FVector L = ElevatorFloor->GetActorLocation();
		ElevatorFloor->SetActorLocation(FVector(L.X, L.Y, FloorDownZ));
	}

	// Find the glowing elevator call-pad (tagged "ElevatorPad"). It is attached to the
	// elevator floor, so it rides up/down with it; stepping onto its footprint toggles
	// the elevator (see Tick).
	Found.Empty();
	UGameplayStatics::GetAllActorsWithTag(GetWorld(), FName("ElevatorPad"), Found);
	if (Found.Num() > 0)
	{
		ElevatorPad = Found[0];
		// The pad is a light beam, not a wall — force collision off at runtime so the
		// player can clip straight through it (the saved-level NoCollision flag does not
		// survive a reload, so we guarantee it here).
		ElevatorPad->SetActorEnableCollision(false);
		// Force Movable so we can ride it up/down at runtime (a spawned StaticMeshActor
		// defaults to Static, which silently ignores SetActorLocation).
		if (USceneComponent* PadRoot = ElevatorPad->GetRootComponent())
		{
			PadRoot->SetMobility(EComponentMobility::Movable);
		}
		// Sit the beam on the (down) floor so its glow appears to rise from the floor.
		const FVector PadL = ElevatorPad->GetActorLocation();
		ElevatorPad->SetActorLocation(FVector(PadL.X, PadL.Y, FloorDownZ + PadZOffset));
	}

	// Reverb-y chime played when the player steps onto the call-pad.
	PadSound = LoadObject<USoundBase>(nullptr, TEXT("/Game/Audio/S_PadPing.S_PadPing"));

	// Spawn the orbit camera at the world origin (detector centre).
	// It stays there permanently; Tab swaps the view target to/from it.
	OrbitCam = GetWorld()->SpawnActor<AOrbitCameraActor>(
		AOrbitCameraActor::StaticClass(), FTransform::Identity);

	// Resolve the Input Action assets (MoveAction/LookAction/...). The mapping CONTEXT itself is
	// built and applied in SetupPlayerInputComponent (in C++ with EKeys). We deliberately do NOT
	// AddMappingContext(DefaultMappingContext) here: SetupPlayerInputComponent runs first (at login)
	// and clears+adds the good context, so re-adding the (null-keyed) asset context here would just
	// layer a broken duplicate on top and fight it.
	DiscoverInputAssets();
}

void AColliderVisCharacter::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);

	// Floor elevator: ride the walkable floor between the detector bottom and middle
	// with ease-in/out (fast). The character rides it via CharacterMovementComponent's
	// moving-base support (it stands on the Movable floor).
	if (bFloorAnimating && ElevatorFloor)
	{
		const float Step = (FloorTravelTime > 0.f) ? (DeltaTime / FloorTravelTime) : 1.f;
		FloorAlpha = FMath::Clamp(FloorAlpha + (FloorTarget > FloorAlpha ? Step : -Step), 0.f, 1.f);
		const float Z = FMath::InterpEaseInOut(FloorDownZ, FloorUpZ, FloorAlpha, 2.0f);
		const FVector L = ElevatorFloor->GetActorLocation();
		// No sweep: a swept move would be blocked by the character standing on the
		// slab. The character is carried by CharacterMovementComponent's moving-base.
		ElevatorFloor->SetActorLocation(FVector(L.X, L.Y, Z), /*bSweep=*/false);
		// Carry the call-pad light beam with the floor so its glow rises from the floor.
		if (ElevatorPad)
		{
			const FVector PadL = ElevatorPad->GetActorLocation();
			ElevatorPad->SetActorLocation(FVector(PadL.X, PadL.Y, Z + PadZOffset), /*bSweep=*/false);
		}
		if (FMath::IsNearlyEqual(FloorAlpha, FloorTarget, 0.001f))
		{
			FloorAlpha = FloorTarget;
			bFloorAnimating = false;
		}
	}

	// Elevator call-pad: toggle the elevator when the player steps onto the pad's
	// 2 m × 2 m footprint (edge-triggered, so it fires once per step-on and re-arms
	// when the player walks off). The pad is a tall light beam spanning both floor
	// levels, so an XY-only test lets the player call it from the bottom or the top.
	if (ElevatorPad)
	{
		const FVector P   = GetActorLocation();
		const FVector Pad = ElevatorPad->GetActorLocation();
		const bool bInside =
			FMath::Abs(P.X - Pad.X) <= PadHalfExtent &&
			FMath::Abs(P.Y - Pad.Y) <= PadHalfExtent;
		if (bInside && !bOnPad)
		{
			OnFloorElevatorToggle();
			if (PadSound)
			{
				UGameplayStatics::PlaySound2D(this, PadSound);
			}
		}
		bOnPad = bInside;
	}

	// Idle / bored timer: count up time since the last input.  Once we cross the
	// threshold, flip bIsBored (read by the AnimBP) and fire OnBecmeBored() once.
	// NoteInput() resets the timer and fires OnExitBored() on any input.
	if (!bIsBored)
	{
		TimeSinceLastInput += DeltaTime;
		if (TimeSinceLastInput >= IdleThreshold)
		{
			bIsBored = true;
			BoredElapsed = 0.f;
			OnBecmeBored();
		}
	}
	else
	{
		// Bored: slowly pan the view left/right as if idly looking around. Purely
		// procedural (no anim asset / AnimBP graph needed); any input clears
		// bIsBored via NoteInput() and stops this. A designer can also drive a body
		// montage from the OnBecmeBored() Blueprint event.
		BoredElapsed += DeltaTime;
		if (AController* C = GetController())
		{
			const float YawDelta = BoredLookSpeed * FMath::Sin(BoredElapsed * BoredLookFreq) * DeltaTime;
			FRotator CR = C->GetControlRotation();
			CR.Yaw += YawDelta;
			C->SetControlRotation(CR);
		}
	}

	// Smoothly interpolate the boom length for RMB zoom in third-person mode.
	// In orbit mode there is nothing to interpolate here.
	if (!bOrbitMode)
	{
		// Third-person: zoom pulls the follow camera in and narrows the FOV so
		// the user can inspect fine detector / event detail.
		const float TargetLength = bZoomHeld ? ZoomedArmLength : DefaultArmLength;
		CameraBoom->TargetArmLength = FMath::FInterpTo(
			CameraBoom->TargetArmLength, TargetLength, DeltaTime, 8.f);

		const float TargetFOV = bZoomHeld ? ZoomedFOV : DefaultFOV;
		FollowCamera->SetFieldOfView(FMath::FInterpTo(
			FollowCamera->FieldOfView, TargetFOV, DeltaTime, 8.f));

		// Keep the IP (world origin) in focus. The scene PP volume has a FIXED DOF
		// focal plane (2200cm) which, when RMB-zoom makes the DOF shallow, blurs the
		// IP. Override the follow camera's focal distance to track camera->IP distance.
		FollowCamera->PostProcessSettings.bOverride_DepthOfFieldFocalDistance = true;
		FollowCamera->PostProcessSettings.DepthOfFieldFocalDistance =
			FVector::Dist(FollowCamera->GetComponentLocation(), FVector::ZeroVector);
		FollowCamera->PostProcessSettings.bOverride_DepthOfFieldFstop = true;
		FollowCamera->PostProcessSettings.DepthOfFieldFstop = 8.0f;

		// Over-the-shoulder: slide the boom socket to the side/up while aiming so the
		// camera looks past the character's shoulder, then back to centre on release.
		const FVector TargetOffset = bZoomHeld ? ZoomedSocketOffset : DefaultSocketOffset;
		CameraBoom->SocketOffset = FMath::VInterpTo(
			CameraBoom->SocketOffset, TargetOffset, DeltaTime, 8.f);

		// Hide the body mesh while zoomed for a clean over-the-shoulder view; restore it
		// on release.  Only toggle on state change to avoid redundant per-frame calls.
		if (bZoomHeld != bMeshHiddenByZoom)
		{
			if (USkeletalMeshComponent* MeshComp = GetMesh())
			{
				MeshComp->SetVisibility(!bZoomHeld, true);
			}
			bMeshHiddenByZoom = bZoomHeld;
		}
	}
	else if (OrbitCam && OrbitCam->Cam)
	{
		// Orbit mode: RMB is a TEMPORARY FOV punch-in on top of the scroll-set radius.
		// Lerp the orbit camera FOV toward the zoomed value while held, back to the
		// resting FOV on release.  The orbit RADIUS is owned by the mouse wheel
		// (OnScroll -> OrbitCam->AddZoom) and is deliberately NOT touched here.
		const float TargetFOV = bZoomHeld ? OrbitZoomedFOV : OrbitDefaultFOV;
		OrbitCam->Cam->SetFieldOfView(FMath::FInterpTo(
			OrbitCam->Cam->FieldOfView, TargetFOV, DeltaTime, 8.f));

		// Keep the IP (world origin) tack-sharp at any FOV punch-in: focus exactly on
		// the camera->IP distance rather than the arm length (robust to any pivot offset).
		OrbitCam->Cam->PostProcessSettings.bOverride_DepthOfFieldFocalDistance = true;
		OrbitCam->Cam->PostProcessSettings.DepthOfFieldFocalDistance =
			FVector::Dist(OrbitCam->Cam->GetComponentLocation(), FVector::ZeroVector);
	}
}

void AColliderVisCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	// SetupPlayerInputComponent can run BEFORE BeginPlay (where DiscoverInputAssets() also runs),
	// in which case the action pointers below would still be null and nothing would bind — leaving
	// the character uncontrollable. Resolve the assets here first so the bindings always happen.
	DiscoverInputAssets();

	// Create the four cutaway-quadrant input actions (Boolean) once. They have no IA
	// asset; we own them in code and map them in the C++ IMC below.
	if (CutawayActions.Num() == 0)
	{
		for (int32 i = 0; i < 4; ++i)
		{
			UInputAction* A = NewObject<UInputAction>(this);
			A->ValueType = EInputActionValueType::Boolean;
			// A "Pressed" trigger so the action fires once on key-down. Without an
			// explicit trigger, trigger-less actions don't reliably emit Started/Triggered.
			A->Triggers.Add(NewObject<UInputTriggerPressed>(A));
			CutawayActions.Add(A);
		}
	}
	if (!FloorElevatorAction)
	{
		FloorElevatorAction = NewObject<UInputAction>(this);
		FloorElevatorAction->ValueType = EInputActionValueType::Boolean;
		FloorElevatorAction->Triggers.Add(NewObject<UInputTriggerPressed>(FloorElevatorAction));
	}
	if (!RespawnAction)
	{
		RespawnAction = NewObject<UInputAction>(this);
		RespawnAction->ValueType = EInputActionValueType::Boolean;
		RespawnAction->Triggers.Add(NewObject<UInputTriggerPressed>(RespawnAction));
	}

	// Build the mapping context ENTIRELY in C++ with EKeys + code-created modifiers.
	// The /Game/Input/IMC_Default asset can't be authored reliably from Python (keys and
	// modifiers serialize as null), so we own the mapping in code here — rebuild-proof and
	// independent of the asset.
	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Subsystem =
		    ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
		{
			UInputMappingContext* IMC = NewObject<UInputMappingContext>(this);

			auto AddSwizzle = [IMC](FEnhancedActionKeyMapping& M)
			{
				UInputModifierSwizzleAxis* S = NewObject<UInputModifierSwizzleAxis>(IMC);
				S->Order = EInputAxisSwizzle::YXZ;          // route key value onto the Y (forward) axis
				M.Modifiers.Add(S);
			};
			auto AddNegate = [IMC](FEnhancedActionKeyMapping& M, bool bX, bool bY, bool bZ)
			{
				UInputModifierNegate* N = NewObject<UInputModifierNegate>(IMC);
				N->bX = bX; N->bY = bY; N->bZ = bZ;
				M.Modifiers.Add(N);
			};
			if (MoveAction)
			{
				AddSwizzle(IMC->MapKey(MoveAction, EKeys::W));                                                 // forward (+Y)
				{ FEnhancedActionKeyMapping& M = IMC->MapKey(MoveAction, EKeys::S); AddSwizzle(M); AddNegate(M, true, true, true); } // back (-Y)
				AddNegate(IMC->MapKey(MoveAction, EKeys::A), true, true, true);                                 // left (-X)
				IMC->MapKey(MoveAction, EKeys::D);                                                              // right (+X)
			}
			if (LookAction)
			{
				FEnhancedActionKeyMapping& M = IMC->MapKey(LookAction, EKeys::Mouse2D);
				AddNegate(M, false, true, false);   // invert mouse Y so up = look up
				// NOTE: the look scale is intentionally NOT applied here as a fixed
				// modifier. It is applied at runtime in Look() as BaseLookScale *
				// LookSensitivity, so the settings-menu sensitivity slider is live.
			}
			if (JumpAction)               IMC->MapKey(JumpAction,               EKeys::SpaceBar);
			if (SwitchModeAction)         IMC->MapKey(SwitchModeAction,         EKeys::Tab);
			if (ZoomAction)               IMC->MapKey(ZoomAction,               EKeys::RightMouseButton);
			if (PlayEventAction)          IMC->MapKey(PlayEventAction,          EKeys::LeftMouseButton);
			if (NextEventAction)          IMC->MapKey(NextEventAction,          EKeys::N);
			if (OpenMenuAction)           IMC->MapKey(OpenMenuAction,           EKeys::Escape);
			if (ToggleDetectorMenuAction) IMC->MapKey(ToggleDetectorMenuAction, EKeys::V);
			if (SprintAction)             IMC->MapKey(SprintAction,             EKeys::LeftShift);
			if (FlyAction)                IMC->MapKey(FlyAction,                EKeys::F);
			if (FlyDownAction)            IMC->MapKey(FlyDownAction,            EKeys::Q);
			if (FlyUpAction)              IMC->MapKey(FlyUpAction,              EKeys::E);
			// Mouse wheel -> orbit dolly.  MouseWheelAxis is already a 1D axis
			// (positive = wheel-up), so no swizzle/negate modifier is needed.
			if (ScrollAction)             IMC->MapKey(ScrollAction,             EKeys::MouseWheelAxis);

			// Cutaway quadrant toggles on number keys 1-4.
			if (CutawayActions.Num() == 4)
			{
				IMC->MapKey(CutawayActions[0], EKeys::One);
				IMC->MapKey(CutawayActions[1], EKeys::Two);
				IMC->MapKey(CutawayActions[2], EKeys::Three);
				IMC->MapKey(CutawayActions[3], EKeys::Four);
			}
			if (FloorElevatorAction) IMC->MapKey(FloorElevatorAction, EKeys::C);
			if (RespawnAction) IMC->MapKey(RespawnAction, EKeys::Z);

			Subsystem->ClearAllMappings();
			Subsystem->AddMappingContext(IMC, 0);
			UE_LOG(LogTemp, Warning, TEXT("[CVInput v4] runtime IMC applied: %d mappings (Move=%s Look=%s)"),
				IMC->GetMappings().Num(), *GetNameSafe(MoveAction), *GetNameSafe(LookAction));
		}
		else { UE_LOG(LogTemp, Error, TEXT("[CVInput v4] no EnhancedInput subsystem")); }
	}
	else { UE_LOG(LogTemp, Error, TEXT("[CVInput v4] SetupPlayerInputComponent: controller not a PlayerController yet")); }

	UEnhancedInputComponent* EIC = Cast<UEnhancedInputComponent>(PlayerInputComponent);
	if (EIC)
	{
		if (MoveAction)        EIC->BindAction(MoveAction,        ETriggerEvent::Triggered, this, &AColliderVisCharacter::Move);
		if (LookAction)        EIC->BindAction(LookAction,        ETriggerEvent::Triggered, this, &AColliderVisCharacter::Look);
		if (JumpAction)        EIC->BindAction(JumpAction,        ETriggerEvent::Started,   this, &AColliderVisCharacter::OnJump);
		if (JumpAction)        EIC->BindAction(JumpAction,        ETriggerEvent::Completed, this, &ACharacter::StopJumping);
		if (NextEventAction)   EIC->BindAction(NextEventAction,   ETriggerEvent::Started,   this, &AColliderVisCharacter::OnNextEvent);
		if (OpenMenuAction)    EIC->BindAction(OpenMenuAction,    ETriggerEvent::Started,   this, &AColliderVisCharacter::OnOpenMenu);
		if (SwitchModeAction)  EIC->BindAction(SwitchModeAction,  ETriggerEvent::Started,   this, &AColliderVisCharacter::OnSwitchMode);
		if (ToggleDetectorMenuAction) EIC->BindAction(ToggleDetectorMenuAction, ETriggerEvent::Started, this, &AColliderVisCharacter::OnToggleDetectorMenu);

		if (ZoomAction)
		{
			EIC->BindAction(ZoomAction, ETriggerEvent::Started,   this, &AColliderVisCharacter::OnZoomStarted);
			EIC->BindAction(ZoomAction, ETriggerEvent::Completed, this, &AColliderVisCharacter::OnZoomCompleted);
		}

		if (PlayEventAction)
		{
			EIC->BindAction(PlayEventAction, ETriggerEvent::Started, this, &AColliderVisCharacter::OnPlayEvent);
		}

		if (DetectorKeyAction)
		{
			EIC->BindAction(DetectorKeyAction, ETriggerEvent::Started, this, &AColliderVisCharacter::OnDetectorKey);
		}

		if (SprintAction)
		{
			EIC->BindAction(SprintAction, ETriggerEvent::Started,   this, &AColliderVisCharacter::OnSprintStarted);
			EIC->BindAction(SprintAction, ETriggerEvent::Completed, this, &AColliderVisCharacter::OnSprintCompleted);
		}

		if (FlyAction)
		{
			EIC->BindAction(FlyAction, ETriggerEvent::Started, this, &AColliderVisCharacter::OnFlyToggle);
		}

		// Q/E — continuous vertical fly movement while held (Triggered fires every
		// frame the key is down).  Handlers no-op unless bFlying.
		if (FlyDownAction)
		{
			EIC->BindAction(FlyDownAction, ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnFlyDown);
		}
		if (FlyUpAction)
		{
			EIC->BindAction(FlyUpAction, ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnFlyUp);
		}

		if (ScrollAction)
		{
			EIC->BindAction(ScrollAction, ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnScroll);
		}

		// Number keys 1-4 toggle the detector phi-quadrant cutaways (MPC_Cutaway).
		if (CutawayActions.Num() == 4)
		{
			EIC->BindAction(CutawayActions[0], ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnCutawayQuadrant1);
			EIC->BindAction(CutawayActions[1], ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnCutawayQuadrant2);
			EIC->BindAction(CutawayActions[2], ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnCutawayQuadrant3);
			EIC->BindAction(CutawayActions[3], ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnCutawayQuadrant4);
		}
		if (FloorElevatorAction)
		{
			EIC->BindAction(FloorElevatorAction, ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnFloorElevatorToggle);
		}
		if (RespawnAction)
		{
			EIC->BindAction(RespawnAction, ETriggerEvent::Triggered, this, &AColliderVisCharacter::OnRespawn);
		}
	}
}

void AColliderVisCharacter::OnCutawayQuadrant1() { ToggleCutawayQuadrant(1); }
void AColliderVisCharacter::OnCutawayQuadrant2() { ToggleCutawayQuadrant(2); }
void AColliderVisCharacter::OnCutawayQuadrant3() { ToggleCutawayQuadrant(3); }
void AColliderVisCharacter::OnCutawayQuadrant4() { ToggleCutawayQuadrant(4); }

void AColliderVisCharacter::OnFloorElevatorToggle()
{
	if (!ElevatorFloor) return;
	FloorTarget = (FloorTarget > 0.5f) ? 0.f : 1.f;   // toggle down <-> up
	bFloorAnimating = true;
	UE_LOG(LogTemp, Log, TEXT("Floor elevator -> %s"), FloorTarget > 0.5f ? TEXT("UP (middle)") : TEXT("DOWN (bottom)"));
}

void AColliderVisCharacter::OnRespawn()
{
	// Z — teleport back to the level PlayerStart (the spawn-in-front-of-detector pose).
	AActor* Start = UGameplayStatics::GetActorOfClass(GetWorld(), APlayerStart::StaticClass());
	if (!Start) return;
	if (UCharacterMovementComponent* Move = GetCharacterMovement())
	{
		Move->StopMovementImmediately();
	}
	SetActorLocationAndRotation(Start->GetActorLocation(), Start->GetActorRotation(),
		/*bSweep=*/false, nullptr, ETeleportType::TeleportPhysics);
	if (AController* C = GetController())
	{
		C->SetControlRotation(Start->GetActorRotation());   // face the spawn direction
	}
	UE_LOG(LogTemp, Log, TEXT("Respawn -> PlayerStart"));
}

void AColliderVisCharacter::ToggleCutawayQuadrant(int32 Quadrant)
{
	// Real-geometry cutaway: each 90° wedge is its own actor tagged CutQuad0..3.
	// Key N (1-4) shows/hides wedge N-1. We toggle COMPONENT visibility (not actor
	// hidden-in-game) so the same hidden state shows in the editor viewport, persists
	// in the saved level, and drives the in-game default (e.g. quadrant 1 off).
	const FName Tag(*FString::Printf(TEXT("CutQuad%d"), Quadrant - 1));
	TArray<AActor*> Found;
	UGameplayStatics::GetAllActorsWithTag(GetWorld(), Tag, Found);
	for (AActor* A : Found)
	{
		if (USceneComponent* RC = A->GetRootComponent())
		{
			RC->SetVisibility(!RC->IsVisible(), /*bPropagateToChildren=*/true);
		}
	}
	UE_LOG(LogTemp, Log, TEXT("Cutaway quadrant %d (%s): toggled %d actor(s)"),
	       Quadrant, *Tag.ToString(), Found.Num());
}

void AColliderVisCharacter::Landed(const FHitResult& Hit)
{
	Super::Landed(Hit);
	if (LandingShake)
	{
		if (APlayerController* PC = Cast<APlayerController>(GetController()))
		{
			PC->ClientStartCameraShake(LandingShake);
		}
	}
}

void AColliderVisCharacter::Move(const FInputActionValue& Value)
{
	{ const FVector2D _v = Value.Get<FVector2D>(); UE_LOG(LogTemp, Warning, TEXT("[CVInput v4] Move (%.2f,%.2f)"), _v.X, _v.Y); }

	NoteInput();

	// Movement is disabled while in orbit mode — the character stays put.
	if (bOrbitMode) return;

	const FVector2D MovementVector = Value.Get<FVector2D>();
	if (Controller)
	{
		const FRotator Rotation = Controller->GetControlRotation();

		if (bFlying)
		{
			// While flying, forward follows the full look direction (pitch included) so the
			// player flies where they aim; strafing stays horizontal.
			const FVector ForwardDir = FRotationMatrix(Rotation).GetUnitAxis(EAxis::X);
			const FVector RightDir   = FRotationMatrix(FRotator(0.f, Rotation.Yaw, 0.f)).GetUnitAxis(EAxis::Y);

			AddMovementInput(ForwardDir, MovementVector.Y);
			AddMovementInput(RightDir,   MovementVector.X);
		}
		else
		{
			const FRotator YawRotation(0.f, Rotation.Yaw, 0.f);

			const FVector ForwardDir = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::X);
			const FVector RightDir   = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::Y);

			AddMovementInput(ForwardDir, MovementVector.Y);
			AddMovementInput(RightDir,   MovementVector.X);
		}
	}
}

void AColliderVisCharacter::Look(const FInputActionValue& Value)
{
	NoteInput();

	// Apply the look scale at runtime (was a fixed IMC scalar modifier before) so the
	// settings-menu mouse-sensitivity slider takes effect immediately.
	const float Scale = BaseLookScale * LookSensitivity;
	const FVector2D LookAxis = Value.Get<FVector2D>() * Scale;

	if (bOrbitMode)
	{
		// Route mouse look to the orbit camera instead of the controller rotation.
		if (OrbitCam)
		{
			OrbitCam->AddOrbitInput(LookAxis.X, -LookAxis.Y);
		}
	}
	else
	{
		AddControllerYawInput(LookAxis.X);
		AddControllerPitchInput(LookAxis.Y);
	}
}

void AColliderVisCharacter::SetLookSensitivity(float V)
{
	// Clamp to a sane positive range so the slider can't zero-out or invert look.
	LookSensitivity = FMath::Clamp(V, 0.05f, 10.0f);
}

void AColliderVisCharacter::NoteInput()
{
	TimeSinceLastInput = 0.f;
	if (bIsBored)
	{
		bIsBored = false;
		OnExitBored();
	}
}

void AColliderVisCharacter::OnJump(const FInputActionValue& Value)
{
	NoteInput();

	// While flying, the Jump key ascends instead of jumping.  Space is a Started-only
	// binding so this is a single upward impulse-style input each press; held ascent
	// would need a Triggered binding, kept simple here per spec.
	if (bFlying)
	{
		AddMovementInput(FVector::UpVector, 1.f);
		return;
	}

	Jump();
}

void AColliderVisCharacter::OnSprintStarted(const FInputActionValue& Value)
{
	NoteInput();
	bSprinting = true;
	ApplyMovementSpeed();
}

void AColliderVisCharacter::OnSprintCompleted(const FInputActionValue& Value)
{
	NoteInput();
	bSprinting = false;
	ApplyMovementSpeed();
}

void AColliderVisCharacter::OnFlyToggle(const FInputActionValue& Value)
{
	NoteInput();

	UCharacterMovementComponent* Move = GetCharacterMovement();
	if (!Move) return;

	bFlying = !bFlying;
	Move->SetMovementMode(bFlying ? MOVE_Flying : MOVE_Walking);
	ApplyMovementSpeed();
}

void AColliderVisCharacter::OnFlyDown(const FInputActionValue& Value)
{
	NoteInput();

	// Q descends only while flying; on the ground it does nothing (left for future).
	// AddMovementInput along world -Z is scaled by the flying movement component
	// (MaxFlySpeed, set by ApplyMovementSpeed via the sprint/fly state).
	if (!bFlying) return;
	AddMovementInput(FVector::UpVector, -1.f);
}

void AColliderVisCharacter::OnFlyUp(const FInputActionValue& Value)
{
	NoteInput();

	// E ascends only while flying; mirrors OnFlyDown along world +Z.
	if (!bFlying) return;
	AddMovementInput(FVector::UpVector, 1.f);
}

void AColliderVisCharacter::ApplyMovementSpeed()
{
	UCharacterMovementComponent* Move = GetCharacterMovement();
	if (!Move) return;

	// Sprint boosts whichever mode is active; otherwise use the base speeds.
	Move->MaxWalkSpeed = bSprinting ? SprintSpeed   : WalkSpeed;
	Move->MaxFlySpeed  = bSprinting ? FlySprintSpeed : FlySpeed;
}

void AColliderVisCharacter::OnSwitchMode(const FInputActionValue& Value)
{
	NoteInput();

	if (!OrbitCam) return;

	APlayerController* PC = Cast<APlayerController>(GetController());
	if (!PC) return;

	bOrbitMode = !bOrbitMode;

	// Clear any zoom state and restore the body mesh on every mode switch: the
	// over-the-shoulder Tick block only runs in third-person, so a mesh hidden by an
	// active zoom must be restored here before we leave (or re-enter) follow mode.
	bZoomHeld = false;
	if (bMeshHiddenByZoom)
	{
		if (USkeletalMeshComponent* MeshComp = GetMesh())
		{
			MeshComp->SetVisibility(true, true);
		}
		bMeshHiddenByZoom = false;
	}

	// Hide the character body while orbiting (the player is inspecting the detector,
	// not the avatar); show it again on return to third-person. This runs after the
	// zoom-restore above so the orbit state is authoritative for mesh visibility.
	if (USkeletalMeshComponent* MeshComp = GetMesh())
	{
		MeshComp->SetVisibility(!bOrbitMode, true);
	}

	// The orbit-FOV interp only runs in the orbit Tick branch, so a temporary
	// RMB punch-in would never revert once we leave orbit mode.  Snap the orbit
	// camera back to its resting FOV here so it's clean on the next entry.
	if (OrbitCam && OrbitCam->Cam)
	{
		OrbitCam->Cam->SetFieldOfView(OrbitDefaultFOV);
	}

	if (bOrbitMode)
	{
		// Switch view to the orbit camera — smooth 0.4 s cubic blend.
		PC->SetViewTargetWithBlend(OrbitCam, 0.4f, VTBlend_Cubic);
	}
	else
	{
		// Return to the follow camera on this character.
		PC->SetViewTargetWithBlend(this, 0.4f, VTBlend_Cubic);
	}
}

void AColliderVisCharacter::OnNextEvent(const FInputActionValue& Value)
{
	NoteInput();

	if (EventDisplayManager)
	{
		EventDisplayManager->LoadNextEvent();
	}
}

void AColliderVisCharacter::OnOpenMenu(const FInputActionValue& Value)
{
	NoteInput();

	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (AColliderVisHUD* HUD = Cast<AColliderVisHUD>(PC->GetHUD()))
		{
			HUD->ToggleMenu();
		}
	}
}

void AColliderVisCharacter::OnToggleDetectorMenu(const FInputActionValue& Value)
{
	// V key opens the same unified options menu (detector section is inside it)
	OnOpenMenu(Value);
}

void AColliderVisCharacter::OnZoomStarted(const FInputActionValue& Value)
{
	NoteInput();
	bZoomHeld = true;   // works in both third-person (arm) and orbit (radius) modes
}

void AColliderVisCharacter::OnZoomCompleted(const FInputActionValue& Value)
{
	NoteInput();
	bZoomHeld = false;
}

void AColliderVisCharacter::OnScroll(const FInputActionValue& Value)
{
	NoteInput();

	const float Axis = Value.Get<float>();
	if (Axis == 0.f) return;

	// Orbit mode only: wheel-up (positive) zooms in, wheel-down zooms out.
	// AddZoom() interprets positive Delta as zoom-in and applies its own 80x
	// scale + radius clamp, so this persistently dollies the orbit radius.
	// Third-person mode intentionally ignores the wheel (kept simple).
	if (bOrbitMode && OrbitCam)
	{
		OrbitCam->AddZoom(Axis * OrbitScrollScale);
	}
}

void AColliderVisCharacter::OnPlayEvent(const FInputActionValue& Value)
{
	NoteInput();

	// LMB — advance to and animate the next event.  Prefer the cached manager (found in
	// BeginPlay); fall back to a world search in case it wasn't present then.
	AEventDisplayManager* Manager = EventDisplayManager;
	if (!Manager)
	{
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(GetWorld(), AEventDisplayManager::StaticClass(), Found);
		if (Found.Num() > 0)
		{
			Manager = Cast<AEventDisplayManager>(Found[0]);
			EventDisplayManager = Manager;   // cache for next time
		}
	}

	if (Manager)
	{
		Manager->PlayNextEventAnimated();
	}
}

void AColliderVisCharacter::OnDetectorKey(const FInputActionValue& Value)
{
	NoteInput();

	if (!VisibilityManager || !VisibilityManager->Config) return;

	// The float value is set by the Scalar input modifier on each key mapping:
	// key 1 → 1.0, key 2 → 2.0, … key 9 → 9.0.
	const int32 Slot = FMath::RoundToInt(Value.Get<float>());
	if (Slot < 1 || Slot > 9) return;

	for (const FSubDetectorEntry& Entry : VisibilityManager->Config->SubDetectors)
	{
		if (Entry.HotkeySlot == Slot)
		{
			VisibilityManager->ToggleSubDetector(Entry.Name);
			break;
		}
	}
}

void AColliderVisCharacter::DiscoverInputAssets()
{
	// Only load if not already assigned via Blueprint defaults
	if (!DefaultMappingContext)
		DefaultMappingContext = LoadObject<UInputMappingContext>(nullptr, TEXT("/Game/Input/IMC_Default.IMC_Default"));
	if (!MoveAction)
		MoveAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Move.IA_Move"));
	if (!LookAction)
		LookAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Look.IA_Look"));
	if (!JumpAction)
		JumpAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Jump.IA_Jump"));
	if (!NextEventAction)
		NextEventAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_NextEvent.IA_NextEvent"));
	if (!OpenMenuAction)
		OpenMenuAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_OpenMenu.IA_OpenMenu"));
	if (!SwitchModeAction)
		SwitchModeAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_SwitchMode.IA_SwitchMode"));
	if (!ToggleDetectorMenuAction)
		ToggleDetectorMenuAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_ToggleDetectorMenu.IA_ToggleDetectorMenu"));
	if (!ZoomAction)
		ZoomAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Zoom.IA_Zoom"));
	if (!PlayEventAction)
		PlayEventAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_PlayEvent.IA_PlayEvent"));
	if (!DetectorKeyAction)
		DetectorKeyAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_DetectorKey.IA_DetectorKey"));

	// Sprint / Fly were added after the original /Game/Input asset set was authored, so the
	// assets may not exist.  Try to discover them, then fall back to transient UInputActions
	// so the LeftShift / F bindings always work without requiring new content to be created.
	if (!SprintAction)
		SprintAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Sprint.IA_Sprint"));
	if (!SprintAction)
		SprintAction = NewObject<UInputAction>(this, TEXT("IA_Sprint_Transient"));

	if (!FlyAction)
		FlyAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_FlyToggle.IA_FlyToggle"));
	if (!FlyAction)
		FlyAction = NewObject<UInputAction>(this, TEXT("IA_FlyToggle_Transient"));

	// Q/E vertical fly movement — added after the original asset set, so discover
	// then fall back to transient UInputActions so the Q/E bindings always work.
	if (!FlyDownAction)
		FlyDownAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_FlyDown.IA_FlyDown"));
	if (!FlyDownAction)
		FlyDownAction = NewObject<UInputAction>(this, TEXT("IA_FlyDown_Transient"));

	if (!FlyUpAction)
		FlyUpAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_FlyUp.IA_FlyUp"));
	if (!FlyUpAction)
		FlyUpAction = NewObject<UInputAction>(this, TEXT("IA_FlyUp_Transient"));

	// Mouse-wheel orbit dolly — added after the original asset set, so discover
	// then fall back to a transient Axis1D action so the wheel always works.
	if (!ScrollAction)
		ScrollAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Scroll.IA_Scroll"));
	if (!ScrollAction)
	{
		ScrollAction = NewObject<UInputAction>(this, TEXT("IA_Scroll_Transient"));
		// MouseWheelAxis is a 1D axis; the action must be Axis1D or Get<float>() is 0.
		ScrollAction->ValueType = EInputActionValueType::Axis1D;
	}
}
