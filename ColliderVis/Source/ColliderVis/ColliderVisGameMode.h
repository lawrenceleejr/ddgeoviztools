#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "ColliderVisGameMode.generated.h"

class ACameraActor;

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
	 * Spawn the default soft/warm cinematic key-fill-rim rig at BeginPlay.
	 * ON by default so PIE matches the editor cinematic render look.  The rig
	 * uses large soft rect lights with volumetric scattering for god rays
	 * through the height fog.  Turn OFF if a level already provides authoritative
	 * imported lights (e.g. a Blender rig placed by Tools/ue5_build_content.py).
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Lighting")
	bool bSpawnDefaultLighting = false;

	/**
	 * Spawn the procedural sci-fi box room at BeginPlay.  OFF by default:
	 * the imported detector geometry / level is authoritative.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Lighting")
	bool bSpawnSciFiRoom = false;

	/**
	 * Spawn a set of cinematic CameraActors at BeginPlay (wide-angle, shallow
	 * depth of field) framing the detector.  Some are static "money shots", some
	 * are animated (orbit / dolly / crane) in Tick with lens flares dialled up.
	 * These are PIE-time cameras for quick capture and a starting point for the
	 * orchestrator's Level Sequences.  ON by default.  (Uses ACameraActor +
	 * per-camera FPostProcessSettings DoF so no CinematicCamera module dep is
	 * needed; the orchestrator can upgrade these to CineCameraActors in-editor.)
	 */
	// Off by default for gameplay performance (7 ticking camera actors). Enable for
	// attract-mode / Movie Render Queue capture.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Cameras")
	bool bSpawnCinematicCameras = false;

	/**
	 * If true, the first animated camera is made the active view target at
	 * BeginPlay so PIE immediately shows the moving cinematic shot instead of the
	 * player pawn.  OFF by default (keeps normal playable view); flip on for a
	 * hands-off "attract mode" / capture session.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Cameras")
	bool bUseCinematicCameraAsView = false;

	/** World-space point the cinematic cameras look at / orbit (collision point). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Cameras")
	FVector CameraTargetLocation = FVector(0.f, 0.f, 150.f);

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

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

	/**
	 * Gated by bSpawnCinematicCameras: spawn several CameraActors (static +
	 * animated) with wide-angle FOV and shallow depth of field for dramatic,
	 * Hollywood-style coverage of the detector.
	 */
	void SetupCinematicCameras();

	/** Animated cameras driven each Tick (orbit / dolly / crane). */
	UPROPERTY()
	TArray<TObjectPtr<ACameraActor>> AnimatedCameras;

	/** Accumulated play time used to drive the animated camera moves. */
	float CameraAnimTime = 0.f;
};
