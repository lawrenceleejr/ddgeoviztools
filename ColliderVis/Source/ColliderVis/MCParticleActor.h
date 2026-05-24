#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "EDM4HEPTypes.h"
#include "MCParticleActor.generated.h"

class UProceduralMeshComponent;
class UEventDisplayConfig;

/**
 * Renders Monte-Carlo truth particles as thin cylinders
 * from their production vertex to their end vertex.
 */
UCLASS()
class COLLIDERVIS_API AMCParticleActor : public AActor
{
	GENERATED_BODY()

public:
	AMCParticleActor();

	void SetParticles(const TArray<FEDMMCParticle>& Particles, const UEventDisplayConfig* Cfg);

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY(VisibleAnywhere)
	UProceduralMeshComponent* LineMesh;

	/** Build a cylinder mesh section from Start to End with given Radius and NumSides. */
	static void BuildCylinder(
		const FVector& Start, const FVector& End, float Radius, int32 NumSides,
		TArray<FVector>& OutVerts, TArray<int32>& OutTris,
		TArray<FVector>& OutNormals, TArray<FVector2D>& OutUVs,
		TArray<FColor>& OutColors);
};
