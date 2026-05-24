// Copyright ColliderVis Project. All Rights Reserved.
#include "OrbitCameraActor.h"
#include "GameFramework/SpringArmComponent.h"
#include "Camera/CameraComponent.h"

AOrbitCameraActor::AOrbitCameraActor()
{
	PrimaryActorTick.bCanEverTick = false;

	// Root sits at the world origin — this is the orbit pivot.
	// Rotating the actor changes where the spring arm points, which changes
	// the camera position while keeping it aimed back at the origin.
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("OrbitPivot"));
	SetRootComponent(Root);

	// Arm extends outward from the pivot; the camera attaches at the far end
	// and inherits the arm's rotation, so it always faces the origin.
	Arm = CreateDefaultSubobject<USpringArmComponent>(TEXT("Arm"));
	Arm->SetupAttachment(Root);
	Arm->TargetArmLength         = 1200.f;   // initial orbit radius
	Arm->bUsePawnControlRotation = false;
	Arm->bInheritPitch           = true;
	Arm->bInheritYaw             = true;
	Arm->bInheritRoll            = false;
	Arm->bDoCollisionTest        = false;    // don't clip through detector geometry
	Arm->bEnableCameraLag        = false;    // precise orbit tracking, no drift

	Cam = CreateDefaultSubobject<UCameraComponent>(TEXT("Cam"));
	Cam->SetupAttachment(Arm, USpringArmComponent::SocketName);
	Cam->bUsePawnControlRotation = false;

	SetActorRotation(FRotator(CurrentPitch, CurrentYaw, 0.f));
}

void AOrbitCameraActor::AddOrbitInput(float DeltaYaw, float DeltaPitch)
{
	CurrentYaw  += DeltaYaw;
	CurrentPitch = FMath::Clamp(CurrentPitch + DeltaPitch, -85.f, 85.f);
	SetActorRotation(FRotator(CurrentPitch, CurrentYaw, 0.f));
}

void AOrbitCameraActor::AddZoom(float Delta)
{
	Arm->TargetArmLength = FMath::Clamp(
		Arm->TargetArmLength - Delta * 80.f,
		MinRadius, MaxRadius);
}
