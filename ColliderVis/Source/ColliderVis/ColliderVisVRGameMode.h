// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "ColliderVisGameMode.h"
#include "ColliderVisVRGameMode.generated.h"

/**
 * Game mode for Meta Quest 3 VR sessions (tethered PCVR or standalone Android).
 * Inherits from AColliderVisGameMode so the post-process volume, soft-box lights,
 * and atmospheric fog are spawned identically to the desktop explore session.
 *
 * The only difference: DefaultPawnClass is AColliderVisVRPawn.
 *
 * Activation:
 *   Tethered / Editor  — set World Settings > GameMode Override to this class.
 *   Standalone Quest   — Config/Android/AndroidGame.ini sets it as the default
 *                        (already done); Android builds will use VR pawn by default.
 */
UCLASS()
class COLLIDERVIS_API AColliderVisVRGameMode : public AColliderVisGameMode
{
	GENERATED_BODY()

public:
	AColliderVisVRGameMode();
};
