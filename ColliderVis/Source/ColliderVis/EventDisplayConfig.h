#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "EventDisplayConfig.generated.h"

/**
 * Data asset controlling how collision event objects are rendered.
 * Create as DA_EventDisplayConfig in the Content Browser.
 */
UCLASS(BlueprintType)
class COLLIDERVIS_API UEventDisplayConfig : public UDataAsset
{
	GENERATED_BODY()

public:
	UEventDisplayConfig();

	/** Calo collections to show, e.g. {"ECalBarrelHits","HCalBarrelHits"} */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collections")
	TArray<FName> EnabledCaloCollections;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tracks")
	bool bShowTracks = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MC Particles")
	bool bShowMCParticles = false;

	/** Spline tube radius in UE cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tracks", meta = (ClampMin = "0.1", ClampMax = "20.0"))
	float TrackTubeRadius = 2.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tracks")
	FLinearColor PositiveTrackColor = FLinearColor(1.0f, 0.4f, 0.1f);   // red-orange

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tracks")
	FLinearColor NegativeTrackColor = FLinearColor(0.1f, 0.7f, 1.0f);   // cyan-blue

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tracks")
	FLinearColor NeutralTrackColor = FLinearColor(1.0f, 1.0f, 1.0f);

	/** Emissive intensity multiplier: EmissiveNits = MomentumGeV * EnergyEmissiveScale */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tracks", meta = (ClampMin = "0.0"))
	float EnergyEmissiveScale = 50.0f;

	/** Calo hit cube half-size in UE cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "CaloHits", meta = (ClampMin = "0.5"))
	float CaloHitBaseSize = 5.0f;

	/** Converts JSON mm positions to UE cm: 0.1 = mm→cm */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Coordinates", meta = (ClampMin = "0.001"))
	float WorldScale = 0.1f;

	/** Python executable name or absolute path, e.g. "python3" */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tools")
	FString PythonExecutable = TEXT("python3");

	/** Absolute path to edm4hep_to_json.py */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Tools")
	FString EDM4HEPScriptPath;
};
