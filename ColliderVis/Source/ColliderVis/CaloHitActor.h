#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "EDM4HEPTypes.h"
#include "CaloHitActor.generated.h"

class UInstancedStaticMeshComponent;
class UEventDisplayConfig;

/**
 * Renders one calorimeter collection's hits as instanced cubes.
 * Energy drives cube scale and emissive intensity via Custom Primitive Data.
 * Create one actor per collection name (ECal, HCal, …).
 */
UCLASS()
class COLLIDERVIS_API ACaloHitActor : public AActor
{
	GENERATED_BODY()

public:
	ACaloHitActor();

	/** Populate instances from a filtered subset of calo hits (same collection). */
	void SetHits(const TArray<FEDMCaloHit>& Hits, const UEventDisplayConfig* Cfg);

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY(VisibleAnywhere)
	UInstancedStaticMeshComponent* ISMC;
};
