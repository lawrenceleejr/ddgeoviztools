#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "DetectorVisibilityConfig.generated.h"

/**
 * One entry describing a named sub-detector group.
 * Actors in the level are grouped by matching their Actor Tags against ActorTags.
 *
 * Developer setup (DA_DetectorVisibility Details panel):
 *   1. Add an entry per sub-detector group.
 *   2. Set Name to a short identifier, e.g. "ECalBarrel".
 *   3. Set ActorTags to the tag(s) shared by all meshes in that group
 *      (ue5_tag_actors.py sets these automatically from manifest.json).
 *   4. Set HotkeySlot to 1–9 to bind it to that number key, or 0 to leave unbound.
 */
USTRUCT(BlueprintType)
struct COLLIDERVIS_API FSubDetectorEntry
{
	GENERATED_BODY()

	/** Human-readable name shown in the visibility panel, e.g. "ECalBarrel" */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	FName Name;

	/** Initial visibility state */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	bool bVisibleByDefault = true;

	/** Color swatch shown in the WBP_DetectorVisibility panel */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	FLinearColor LabelColor = FLinearColor::White;

	/**
	 * Number key (1–9) that toggles this group's visibility at runtime.
	 * 0 = unbound.  Each slot should be unique across all entries.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, meta = (ClampMin = "0", ClampMax = "9"))
	int32 HotkeySlot = 0;

	/**
	 * Actor tags that identify meshes belonging to this sub-detector.
	 * Set via Tools/ue5_tag_actors.py after importing GLTF meshes.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	TArray<FName> ActorTags;
};

/**
 * Data asset listing all sub-detectors and their visibility metadata.
 * Create as DA_DetectorVisibility; populate from manifest.json via ue5_tag_actors.py.
 */
UCLASS(BlueprintType)
class COLLIDERVIS_API UDetectorVisibilityConfig : public UDataAsset
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Sub-Detectors")
	TArray<FSubDetectorEntry> SubDetectors;
};
