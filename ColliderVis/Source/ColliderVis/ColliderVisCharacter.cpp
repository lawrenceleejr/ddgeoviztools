// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisCharacter.h"
#include "OrbitCameraActor.h"
#include "EventDisplayManager.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputMappingContext.h"
#include "InputAction.h"
#include "Kismet/GameplayStatics.h"

AColliderVisCharacter::AColliderVisCharacter()
{
	PrimaryActorTick.bCanEverTick = true;   // needed for arm-length zoom interpolation

	// Spring Arm — cinematic lag for smooth follow
	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(RootComponent);
	CameraBoom->TargetArmLength          = DefaultArmLength;
	CameraBoom->bUsePawnControlRotation  = true;
	CameraBoom->bEnableCameraLag         = true;
	CameraBoom->CameraLagSpeed           = 5.f;
	CameraBoom->bEnableCameraRotationLag = true;
	CameraBoom->CameraRotationLagSpeed   = 10.f;
	CameraBoom->bDoCollisionTest         = true;

	// Follow Camera
	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;

	// Character movement defaults
	GetCharacterMovement()->bOrientRotationToMovement        = true;
	GetCharacterMovement()->RotationRate                     = FRotator(0.f, 500.f, 0.f);
	GetCharacterMovement()->JumpZVelocity                    = 700.f;
	GetCharacterMovement()->AirControl                       = 0.35f;
	GetCharacterMovement()->MaxWalkSpeed                     = 500.f;
	GetCharacterMovement()->MinAnalogWalkSpeed               = 20.f;
	GetCharacterMovement()->BrakingDecelerationWalking       = 2000.f;

	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw   = false;
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

	// Spawn the orbit camera at the world origin (detector centre).
	// It stays there permanently; Tab swaps the view target to/from it.
	OrbitCam = GetWorld()->SpawnActor<AOrbitCameraActor>(
		AOrbitCameraActor::StaticClass(), FTransform::Identity);

	// Register Enhanced Input mapping context
	DiscoverInputAssets();

	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Subsystem =
		    ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
		{
			if (DefaultMappingContext)
			{
				Subsystem->AddMappingContext(DefaultMappingContext, 0);
			}
		}
	}
}

void AColliderVisCharacter::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);

	// Smoothly interpolate the boom length for RMB zoom in third-person mode.
	// In orbit mode there is nothing to interpolate here.
	if (!bOrbitMode)
	{
		// Third-person: RMB zooms the follow camera toward the character.
		const float TargetLength = bZoomHeld ? ZoomedArmLength : DefaultArmLength;
		CameraBoom->TargetArmLength = FMath::FInterpTo(
			CameraBoom->TargetArmLength, TargetLength, DeltaTime, 8.f);
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
	if (UEnhancedInputComponent* EIC = Cast<UEnhancedInputComponent>(PlayerInputComponent))
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
	}
}

void AColliderVisCharacter::OnLanded(const FHitResult& Hit)
{
	Super::OnLanded(Hit);
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
	// Delegate to Blueprint via implementable event on the HUD or a widget manager
	// The WBP_EventMenu widget handles show/hide in Blueprint
}

void AColliderVisCharacter::OnToggleDetectorMenu(const FInputActionValue& Value)
{
	// Handled by Blueprint HUD via Blueprint implementable event
}

void AColliderVisCharacter::OnZoomStarted(const FInputActionValue& Value)
{
	bZoomHeld = true;   // works in both third-person (arm) and orbit (radius) modes
}

void AColliderVisCharacter::OnZoomCompleted(const FInputActionValue& Value)
{
	bZoomHeld = false;
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
}
