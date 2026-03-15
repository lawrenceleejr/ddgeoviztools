#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "ColliderVisVizGameMode.generated.h"

/**
 * Movie/Still mode — spectator pawn, auto-possess cinematic camera.
 * No character movement; cinematic fly-through input only.
 */
UCLASS()
class COLLIDERVIS_API AColliderVisVizGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AColliderVisVizGameMode();

protected:
	virtual void BeginPlay() override;
};
