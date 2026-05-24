// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisVRPawn.h"
#include "EventDisplayManager.h"
#include "Camera/CameraComponent.h"
#include "MotionControllerComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputMappingContext.h"
#include "InputAction.h"
#include "Kismet/GameplayStatics.h"
#include "ColliderVisHUD.h"

AColliderVisVRPawn::AColliderVisVRPawn()
{
	PrimaryActorTick.bCanEverTick = true;

	// Root — the tracking-space floor origin.  All VR components live here.
	VROrigin = CreateDefaultSubobject<USceneComponent>(TEXT("VROrigin"));
	SetRootComponent(VROrigin);

	// Camera follows the HMD pose automatically when OpenXR is active.
	// bUsePawnControlRotation must be false so the engine doesn't fight the HMD.
	VRCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("VRCamera"));
	VRCamera->SetupAttachment(VROrigin);
	VRCamera->bUsePawnControlRotation = false;

	// Motion controllers — positional tracking for future hand visuals / pointer rays.
	LeftHand = CreateDefaultSubobject<UMotionControllerComponent>(TEXT("LeftHand"));
	LeftHand->SetupAttachment(VROrigin);
	LeftHand->MotionSource = FName("Left");

	RightHand = CreateDefaultSubobject<UMotionControllerComponent>(TEXT("RightHand"));
	RightHand->SetupAttachment(VROrigin);
	RightHand->MotionSource = FName("Right");
}

void AColliderVisVRPawn::BeginPlay()
{
	Super::BeginPlay();

	// Find EventDisplayManager in the level
	TArray<AActor*> Found;
	UGameplayStatics::GetAllActorsOfClass(GetWorld(), AEventDisplayManager::StaticClass(), Found);
	if (Found.Num() > 0)
	{
		EventDisplayManager = Cast<AEventDisplayManager>(Found[0]);
	}

	DiscoverInputAssets();

	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Sub =
		    ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
		{
			if (VRMappingContext)
			{
				Sub->AddMappingContext(VRMappingContext, 0);
			}
		}
	}
}

void AColliderVisVRPawn::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);

	if (bOrbitMode)
	{
		// Smoothly zoom the orbit radius toward the target (set by bZoomHeld).
		const float TargetRadius = bZoomHeld ? ZoomedOrbitRadius : DefaultOrbitRadius;
		OrbitRadius = FMath::FInterpTo(OrbitRadius, TargetRadius, DeltaTime, 6.f);
		UpdateOrbitPosition();
	}
}

void AColliderVisVRPawn::UpdateOrbitPosition()
{
	// Convert spherical coordinates to world-space Cartesian.
	const float YawRad   = FMath::DegreesToRadians(OrbitYaw);
	const float PitchRad = FMath::DegreesToRadians(OrbitPitch);

	const FVector NewPos(
		OrbitRadius * FMath::Cos(PitchRad) * FMath::Cos(YawRad),
		OrbitRadius * FMath::Cos(PitchRad) * FMath::Sin(YawRad),
		OrbitRadius * FMath::Sin(PitchRad)
	);

	SetActorLocation(NewPos);

	// Orient the pawn so its forward axis points toward the origin.
	// The HMD then adds its own tracking rotation on top — the player still
	// has natural head freedom while broadly facing the detector.
	const FRotator FaceOrigin = (FVector::ZeroVector - NewPos).GetSafeNormal().Rotation();
	SetActorRotation(FaceOrigin);
}

void AColliderVisVRPawn::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	if (UEnhancedInputComponent* EIC = Cast<UEnhancedInputComponent>(PlayerInputComponent))
	{
		if (MoveAction)
			EIC->BindAction(MoveAction, ETriggerEvent::Triggered, this, &AColliderVisVRPawn::OnMove);

		if (TurnAction)
			EIC->BindAction(TurnAction, ETriggerEvent::Triggered, this, &AColliderVisVRPawn::OnTurn);

		if (SwitchModeAction)
			EIC->BindAction(SwitchModeAction, ETriggerEvent::Started, this, &AColliderVisVRPawn::OnSwitchMode);

		if (ZoomAction)
		{
			EIC->BindAction(ZoomAction, ETriggerEvent::Started,   this, &AColliderVisVRPawn::OnZoomStarted);
			EIC->BindAction(ZoomAction, ETriggerEvent::Completed, this, &AColliderVisVRPawn::OnZoomCompleted);
		}

		if (NextEventAction)
			EIC->BindAction(NextEventAction, ETriggerEvent::Started, this, &AColliderVisVRPawn::OnNextEvent);

		if (OpenMenuAction)
			EIC->BindAction(OpenMenuAction, ETriggerEvent::Started, this, &AColliderVisVRPawn::OnOpenMenu);
	}
}

void AColliderVisVRPawn::OnMove(const FInputActionValue& Value)
{
	// Movement is suppressed in orbit mode — the pawn position is managed
	// by UpdateOrbitPosition() instead.
	if (bOrbitMode) return;

	const FVector2D Axis = Value.Get<FVector2D>();
	const float DT = GetWorld()->GetDeltaSeconds();

	// Move relative to where the camera is looking, flattened to the horizontal plane
	// so the player doesn't fly up/down when looking up at the detector.
	FVector CamForward = VRCamera->GetForwardVector();
	CamForward.Z = 0.f;
	if (!CamForward.Normalize()) return;

	const FVector Right = FVector::CrossProduct(FVector::UpVector, CamForward);

	AddActorWorldOffset(CamForward * Axis.Y * MoveSpeed * DT);
	AddActorWorldOffset(Right      * Axis.X * MoveSpeed * DT);
}

void AColliderVisVRPawn::OnTurn(const FInputActionValue& Value)
{
	const FVector2D Axis = Value.Get<FVector2D>();
	const float DT = GetWorld()->GetDeltaSeconds();

	if (bOrbitMode)
	{
		// Rotate the orbit around the detector origin.
		// Negate Y so stick-up = camera moves upward on the sphere.
		OrbitYaw   += Axis.X * OrbitRotateSpeed * DT;
		OrbitPitch  = FMath::Clamp(OrbitPitch - Axis.Y * OrbitRotateSpeed * DT, -80.f, 80.f);
		// Position is written immediately so there is no one-frame lag.
		UpdateOrbitPosition();
	}
	else
	{
		// Smooth yaw turn: lets players rotate in place without physically spinning.
		// Pitch is intentionally omitted — the HMD handles up/down look.
		AddActorWorldRotation(FRotator(0.f, Axis.X * TurnSpeed * DT, 0.f));
	}
}

void AColliderVisVRPawn::OnSwitchMode(const FInputActionValue& Value)
{
	bOrbitMode = !bOrbitMode;

	if (bOrbitMode)
	{
		// Place the pawn on the default orbit sphere, facing the origin.
		OrbitRadius = DefaultOrbitRadius;
		UpdateOrbitPosition();
	}
	else
	{
		// Return to world origin so the player stands inside the detector.
		SetActorLocation(FVector::ZeroVector);
		SetActorRotation(FRotator::ZeroRotator);
		bZoomHeld = false;
	}
}

void AColliderVisVRPawn::OnZoomStarted(const FInputActionValue& Value)
{
	if (bOrbitMode)
	{
		bZoomHeld = true;
	}
}

void AColliderVisVRPawn::OnZoomCompleted(const FInputActionValue& Value)
{
	bZoomHeld = false;
}

void AColliderVisVRPawn::OnNextEvent(const FInputActionValue& Value)
{
	if (EventDisplayManager)
	{
		EventDisplayManager->LoadNextEvent();
	}
}

void AColliderVisVRPawn::OnOpenMenu(const FInputActionValue& Value)
{
	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (AColliderVisHUD* HUD = Cast<AColliderVisHUD>(PC->GetHUD()))
		{
			HUD->ToggleMenu();
		}
	}
}

void AColliderVisVRPawn::DiscoverInputAssets()
{
	// Loads assets by path if not already assigned in the Blueprint child.
	// VR uses its own IMC so controller axes don't conflict with keyboard bindings.
	if (!VRMappingContext)
		VRMappingContext = LoadObject<UInputMappingContext>(nullptr, TEXT("/Game/Input/IMC_VR.IMC_VR"));
	if (!MoveAction)
		MoveAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Move.IA_Move"));
	if (!TurnAction)
		TurnAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Look.IA_Look"));
	if (!SwitchModeAction)
		SwitchModeAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_SwitchMode.IA_SwitchMode"));
	if (!ZoomAction)
		ZoomAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_Zoom.IA_Zoom"));
	if (!NextEventAction)
		NextEventAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_NextEvent.IA_NextEvent"));
	if (!OpenMenuAction)
		OpenMenuAction = LoadObject<UInputAction>(nullptr, TEXT("/Game/Input/IA_OpenMenu.IA_OpenMenu"));
}
