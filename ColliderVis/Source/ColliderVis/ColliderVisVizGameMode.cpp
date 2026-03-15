#include "ColliderVisVizGameMode.h"
#include "ColliderVisCineCameraActor.h"
#include "GameFramework/SpectatorPawn.h"
#include "Kismet/GameplayStatics.h"

AColliderVisVizGameMode::AColliderVisVizGameMode()
{
	DefaultPawnClass = ASpectatorPawn::StaticClass();
	bStartPlayersAsSpectators = true;
}

void AColliderVisVizGameMode::BeginPlay()
{
	Super::BeginPlay();

	// Auto-possess the first BP_CineCamera in the level
	TArray<AActor*> Cameras;
	UGameplayStatics::GetAllActorsOfClass(
		GetWorld(), AColliderVisCineCameraActor::StaticClass(), Cameras);

	if (Cameras.Num() > 0)
	{
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(GetWorld(), 0))
		{
			PC->SetViewTargetWithBlend(Cameras[0], 1.5f, VTBlend_Cubic);
		}
	}
}
