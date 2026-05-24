#include "ColliderVisCineCameraActor.h"
#include "EventDisplayManager.h"
#include "Camera/CameraComponent.h"
#include "Kismet/GameplayStatics.h"

AColliderVisCineCameraActor::AColliderVisCineCameraActor()
{
	PrimaryActorTick.bCanEverTick = true;

	UCameraComponent* Cam = GetCameraComponent();
	if (Cam)
	{
		// 50mm full-frame equivalent field of view (~39.6°)
		Cam->FieldOfView = 39.6f;

		// Depth of field via PostProcessSettings (no CinematicCamera plugin needed)
		FPostProcessSettings& PP = Cam->PostProcessSettings;

		// f/1.8 aperture — shallow, cinematic DoF
		PP.bOverride_DepthOfFieldFstop = true;
		PP.DepthOfFieldFstop           = 1.8f;

		// Starting focal distance — UpdateFocusToCentroid will animate this each tick
		PP.bOverride_DepthOfFieldFocalDistance = true;
		PP.DepthOfFieldFocalDistance           = 500.f;

		// Full-frame 36mm sensor width for physically correct CoC calculations
		PP.bOverride_DepthOfFieldSensorWidth = true;
		PP.DepthOfFieldSensorWidth           = 36.f;
	}
}

void AColliderVisCineCameraActor::BeginPlay()
{
	Super::BeginPlay();

	if (!EventDisplayManager)
	{
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(GetWorld(), AEventDisplayManager::StaticClass(), Found);
		if (Found.Num() > 0)
		{
			EventDisplayManager = Cast<AEventDisplayManager>(Found[0]);
		}
	}
}

void AColliderVisCineCameraActor::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	UpdateFocusToCentroid(DeltaTime);
}

void AColliderVisCineCameraActor::UpdateFocusToCentroid(float DeltaTime, float InterpSpeed)
{
	if (!EventDisplayManager) return;

	UCameraComponent* Cam = GetCameraComponent();
	if (!Cam) return;

	const FVector  Centroid    = EventDisplayManager->GetEventCentroid();
	const float    TargetDist  = FVector::Dist(GetActorLocation(), Centroid);
	float&         FocalDist   = Cam->PostProcessSettings.DepthOfFieldFocalDistance;

	FocalDist = FMath::FInterpTo(FocalDist, TargetDist, DeltaTime, InterpSpeed);
}
