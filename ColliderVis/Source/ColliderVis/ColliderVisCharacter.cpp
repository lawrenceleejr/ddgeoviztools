#include "ColliderVisCharacter.h"
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
	PrimaryActorTick.bCanEverTick = false;

	// Spring Arm — cinematic lag for smooth follow
	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(RootComponent);
	CameraBoom->TargetArmLength          = 400.f;
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
	AddControllerYawInput(LookAxis.X);
	AddControllerPitchInput(LookAxis.Y);
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

void AColliderVisCharacter::OnSwitchMode(const FInputActionValue& Value)
{
	// Switch to Viz game mode
	UGameplayStatics::OpenLevel(GetWorld(), FName(*GetWorld()->GetName()), false,
	                             TEXT("game=/Script/ColliderVis.ColliderVisVizGameMode"));
}

void AColliderVisCharacter::OnToggleDetectorMenu(const FInputActionValue& Value)
{
	// Handled by Blueprint HUD via Blueprint implementable event
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
}
