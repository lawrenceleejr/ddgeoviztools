// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisVRGameMode.h"
#include "ColliderVisVRPawn.h"

AColliderVisVRGameMode::AColliderVisVRGameMode()
{
	// Swap the pawn class; everything else (post-process, lights, fog)
	// is inherited from AColliderVisGameMode::BeginPlay → SetupAtmosphere().
	DefaultPawnClass = AColliderVisVRPawn::StaticClass();
}
