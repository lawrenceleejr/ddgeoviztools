#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "DetectorVisibilityConfig.generated.h"

/**
 * One entry describing a named sub-detector group.
 * Actors in the level are grouped by matching their Actor Tags against ActorTags.
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
