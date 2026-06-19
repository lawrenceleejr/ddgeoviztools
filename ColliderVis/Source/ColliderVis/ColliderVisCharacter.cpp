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
#include "InputModifiers.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
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
	CameraBoom->bEnableCameraLag         = true;
	CameraBoom->CameraLagSpeed           = 20.f;   // light position smoothing only
	CameraBoom->bEnableCameraRotationLag = false;  // 1:1 mouse-look (no rotation smoothing — was sluggish)
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
	}
	else if (OrbitCam)
	{
		// Orbit mode: RMB zooms the orbit radius toward/away from the origin.
		const float TargetRadius = bZoomHeld ? ZoomedOrbitRadius : DefaultOrbitRadius;
		OrbitCam->Arm->TargetArmLength = FMath::FInterpTo(
			OrbitCam->Arm->TargetArmLength, TargetRadius, DeltaTime, 6.f);
	}
}

void AColliderVisCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	// SetupPlayerInputComponent can run BEFORE BeginPlay (where DiscoverInputAssets() also runs),
	// in which case the action pointers below would still be null and nothing would bind — leaving
	// the character uncontrollable. Resolve the assets here first so the bindings always happen.
	DiscoverInputAssets();

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
			auto AddScalar = [IMC](FEnhancedActionKeyMapping& M, float Scale)
			{
				UInputModifierScalar* Sc = NewObject<UInputModifierScalar>(IMC);
				Sc->Scalar = FVector(Scale, Scale, Scale);
				M.Modifiers.Add(Sc);
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
				AddScalar(M, 2.0f);                 // mouse sensitivity
			}
			if (JumpAction)               IMC->MapKey(JumpAction,               EKeys::SpaceBar);
			if (SwitchModeAction)         IMC->MapKey(SwitchModeAction,         EKeys::Tab);
			if (ZoomAction)               IMC->MapKey(ZoomAction,               EKeys::RightMouseButton);
			if (NextEventAction)          IMC->MapKey(NextEventAction,          EKeys::N);
			if (OpenMenuAction)           IMC->MapKey(OpenMenuAction,           EKeys::Escape);
			if (ToggleDetectorMenuAction) IMC->MapKey(ToggleDetectorMenuAction, EKeys::V);

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
		if (JumpAction)        EIC->BindAction(JumpAction,        ETriggerEvent::Started,   this, &ACharacter::Jump);
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

		if (DetectorKeyAction)
		{
			EIC->BindAction(DetectorKeyAction, ETriggerEvent::Started, this, &AColliderVisCharacter::OnDetectorKey);
		}
	}
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

	// Movement is disabled while in orbit mode — the character stays put.
	if (bOrbitMode) return;

	const FVector2D MovementVector = Value.Get<FVector2D>();
	if (Controller)
	{
		const FRotator Rotation = Controller->GetControlRotation();
		const FRotator YawRotation(0.f, Rotation.Yaw, 0.f);

		const FVector ForwardDir = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::X);
		const FVector RightDir   = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::Y);

		AddMovementInput(ForwardDir, MovementVector.Y);
		AddMovementInput(RightDir,   MovementVector.X);
	}
}

void AColliderVisCharacter::Look(const FInputActionValue& Value)
{
	const FVector2D LookAxis = Value.Get<FVector2D>();

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

void AColliderVisCharacter::OnSwitchMode(const FInputActionValue& Value)
{
	if (!OrbitCam) return;

	APlayerController* PC = Cast<APlayerController>(GetController());
	if (!PC) return;

	bOrbitMode = !bOrbitMode;

	if (bOrbitMode)
	{
		// Switch view to the orbit camera — smooth 0.4 s cubic blend.
		PC->SetViewTargetWithBlend(OrbitCam, 0.4f, VTBlend_Cubic);
	}
	else
	{
		// Return to the follow camera on this character.
		PC->SetViewTargetWithBlend(this, 0.4f, VTBlend_Cubic);
		// Reset arm length so any zoom state is cleared on re-entry.
		bZoomHeld = false;
	}
}

void AColliderVisCharacter::OnNextEvent(const FInputActionValue& Value)
{
	if (EventDisplayManager)
	{
		EventDisplayManager->LoadNextEvent();
	}
}

void AColliderVisCharacter::OnOpenMenu(const FInputActionValue& Value)
{
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
	bZoomHeld = true;   // works in both third-person (arm) and orbit (radius) modes
}

void AColliderVisCharacter::OnZoomCompleted(const FInputActionValue& Value)
{
	bZoomHeld = false;
}

void AColliderVisCharacter::OnDetectorKey(const FInputActionValue& Value)
{
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
	if (!DetectorKeyAction)
		DetectorKeyAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_DetectorKey.IA_DetectorKey"));
}
