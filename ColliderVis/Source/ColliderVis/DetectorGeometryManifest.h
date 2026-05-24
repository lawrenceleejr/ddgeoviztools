#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "DetectorGeometryManifest.generated.h"

/**
 * One sub-detector entry as exported by Tools/blend_to_ue5.py manifest.json.
 */
USTRUCT(BlueprintType)
struct COLLIDERVIS_API FSubDetectorManifestEntry
{
	GENERATED_BODY()

	/** Object name (from Blender scene, matches GLTF filename stem) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	FString Name;

	/** Relative path to GLTF file inside the export directory */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	FString GltfFile;

	/** PBR base color (linear) from Principled BSDF */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	FLinearColor BaseColor = FLinearColor::White;

	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	float Metallic = 0.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	float Roughness = 0.5f;

	/** Actor tags to assign after UE5 import (matches DetectorVisibilityConfig) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite)
	TArray<FName> ActorTags;
};

/**
 * Stores the parsed contents of manifest.json produced by blend_to_ue5.py.
 * Create DA_DetectorGeometryManifest and populate via the editor Python script
 * Tools/ue5_tag_actors.py, or fill manually from the JSON output.
 */
UCLASS(BlueprintType)
class COLLIDERVIS_API UDetectorGeometryManifest : public UDataAsset
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Manifest")
	TArray<FSubDetectorManifestEntry> SubDetectors;
};
