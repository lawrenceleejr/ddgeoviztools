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

	/**
	 * Spawn a procedural sci-fi room (floor + ceiling + four walls) at the
	 * world origin.  Uses /Engine/BasicShapes/Plane.Plane and a dynamic
	 * dark-metallic material so no content-browser setup is required —
	 * the level always has something for the third-person character to
	 * stand on, even on a blank default map.
	 */
	void SpawnSciFiRoom();
};
