#pragma once

#include "CoreMinimal.h"
#include "EDM4HEPTypes.generated.h"

/** A reconstructed charged particle track: a polyline of 3D points */
USTRUCT(BlueprintType)
struct COLLIDERVIS_API FEDMTrack
{
	GENERATED_BODY()

	/** World-space positions in mm (converted to cm on spawn, WorldScale=0.1) */
	UPROPERTY(BlueprintReadOnly)
	TArray<FVector> Points;

	/** Electric charge: +1, -1, or 0 */
	UPROPERTY(BlueprintReadOnly)
	float Charge = 0.f;

	/** Total momentum magnitude in GeV/c */
	UPROPERTY(BlueprintReadOnly)
	float MomentumGeV = 0.f;

	/** PDG particle ID code */
	UPROPERTY(BlueprintReadOnly)
	int32 PDG = 0;
};

/** A single calorimeter energy deposit */
USTRUCT(BlueprintType)
struct COLLIDERVIS_API FEDMCaloHit
{
	GENERATED_BODY()

	/** Hit centre position in mm */
	UPROPERTY(BlueprintReadOnly)
	FVector Position = FVector::ZeroVector;

	/** Deposited energy in GeV */
	UPROPERTY(BlueprintReadOnly)
	float EnergyGeV = 0.f;

	/** EDM4HEP collection name, e.g. "ECalBarrelHits" */
	UPROPERTY(BlueprintReadOnly)
	FString CollectionName;
};

/** A Monte-Carlo truth particle */
USTRUCT(BlueprintType)
struct COLLIDERVIS_API FEDMMCParticle
{
	GENERATED_BODY()

	/** Production vertex in mm */
	UPROPERTY(BlueprintReadOnly)
	FVector Vertex = FVector::ZeroVector;

	/** Decay / end vertex in mm */
	UPROPERTY(BlueprintReadOnly)
	FVector EndVertex = FVector::ZeroVector;

	/** 3-momentum vector in GeV/c */
	UPROPERTY(BlueprintReadOnly)
	FVector MomentumGeV = FVector::ZeroVector;

	/** PDG particle ID code */
	UPROPERTY(BlueprintReadOnly)
	int32 PDG = 0;

	/** Electric charge */
	UPROPERTY(BlueprintReadOnly)
	float Charge = 0.f;

	/** Generator status (1 = stable final state) */
	UPROPERTY(BlueprintReadOnly)
	int32 Status = 0;
};

/** One collision event containing all reconstructed and truth objects */
USTRUCT(BlueprintType)
struct COLLIDERVIS_API FEDMEvent
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly)
	int32 EventNumber = 0;

	UPROPERTY(BlueprintReadOnly)
	int32 RunNumber = 0;

	UPROPERTY(BlueprintReadOnly)
	TArray<FEDMTrack> Tracks;

	UPROPERTY(BlueprintReadOnly)
	TArray<FEDMCaloHit> CaloHits;

	UPROPERTY(BlueprintReadOnly)
	TArray<FEDMMCParticle> MCParticles;
};
