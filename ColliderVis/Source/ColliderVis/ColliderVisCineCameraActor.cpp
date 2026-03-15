#include "ColliderVisCineCameraActor.h"
#include "EventDisplayManager.h"
#include "CineCameraComponent.h"
#include "Kismet/GameplayStatics.h"

AColliderVisCineCameraActor::AColliderVisCineCameraActor()
{
	PrimaryActorTick.bCanEverTick = true;

	UCineCameraComponent* CineCam = GetCineCameraComponent();
	if (CineCam)
	{
		// Anamorphic 50mm lens preset
		CineCam->CurrentFocalLength  = 50.f;
		CineCam->CurrentAperture     = 1.8f;   // f/1.8 — shallower DoF, more cinematic

		// Focus tracking — will be updated to event centroid each tick
		CineCam->FocusSettings.FocusMethod = ECameraFocusMethod::Manual;
		CineCam->FocusSettings.ManualFocusDistance = 500.f;

		// Film back: full-frame 35mm
		CineCam->Filmback.SensorWidth  = 36.f;
		CineCam->Filmback.SensorHeight = 24.f;
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

	UCineCameraComponent* CineCam = GetCineCameraComponent();
	if (!CineCam) return;

	const FVector Centroid = EventDisplayManager->GetEventCentroid();
	const float TargetDist = FVector::Dist(GetActorLocation(), Centroid);

	CineCam->FocusSettings.ManualFocusDistance = FMath::FInterpTo(
		CineCam->FocusSettings.ManualFocusDistance,
		TargetDist,
		DeltaTime,
		InterpSpeed);
}
