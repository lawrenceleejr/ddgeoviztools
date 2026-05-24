#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "ColliderVisGameMode.generated.h"

/**
 * Explore mode — third-person playable character.
 * Also owns cinematic post-process / atmosphere setup spawned at BeginPlay.
 */
UCLASS()
class COLLIDERVIS_API AColliderVisGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AColliderVisGameMode();

protected:
	virtual void BeginPlay() override;

private:
	/** Spawn the Lumen/Path Tracer post-process volume and atmospheric actors */
	void SetupAtmosphere();
};
