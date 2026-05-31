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

	/**
	 * Spawn the legacy hardcoded "clean-room" rect-light rig at BeginPlay.
	 * OFF by default: the imported Blender light rig (placed in the level by
	 * Tools/ue5_build_content.py) is authoritative.  Flip this on for a blank
	 * map with no imported lights.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Lighting")
	bool bSpawnDefaultLighting = false;

	/**
	 * Spawn the procedural sci-fi box room at BeginPlay.  OFF by default:
	 * the imported detector geometry / level is authoritative.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Lighting")
	bool bSpawnSciFiRoom = false;

protected:
	virtual void BeginPlay() override;

private:
	/**
	 * Always-on: spawn the Lumen post-process volume, low ambient sky light, and
	 * volumetric height fog.  These provide the colour grade and the god-ray
	 * shafts and are kept regardless of which light rig is used.
	 */
	void SetupPostProcessAndFog();

	/**
	 * Gated by bSpawnDefaultLighting: the legacy four-rect-light "clean-room"
	 * rig.  Superseded by the imported Blender lights when those are present.
	 */
	void SetupDefaultLightRig();

	/**
	 * Spawn a procedural sci-fi room (floor + ceiling + four walls) at the
	 * world origin.  Uses /Engine/BasicShapes/Plane.Plane and a dynamic
	 * dark-metallic material so no content-browser setup is required.
	 * Gated by bSpawnSciFiRoom.
	 */
	void SpawnSciFiRoom();
};
