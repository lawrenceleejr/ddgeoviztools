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
 *
 * Supports propagation-time reveal: each truth line grows from its production
 * vertex toward its end vertex as the spherical animation front (radius from
 * the collision center) advances. The mesh section is rebuilt on reveal calls
 * (truth-particle counts are small, so this stays cheap).
 */
UCLASS()
class COLLIDERVIS_API AMCParticleActor : public AActor
{
	GENERATED_BODY()

public:
	AMCParticleActor();

	void SetParticles(const TArray<FEDMMCParticle>& Particles, const UEventDisplayConfig* Cfg);

	/** Largest end-vertex radius from origin (UE cm) — for front sizing. */
	float GetMaxRadius() const { return MaxRadius; }

	/**
	 * Reveal each truth line up to the spherical front radius (UE cm). Each
	 * line is drawn from its vertex to whichever comes first: its end vertex
	 * or the point where the line crosses FrontRadius.
	 */
	void SetRevealRadius(float FrontRadius);

	/** Draw all lines fully (final state). */
	void RevealAll();

	/** Draw nothing (animation start state). */
	void HideAll();

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY(VisibleAnywhere)
	UProceduralMeshComponent* LineMesh;

	/** Cached world-space (already WorldScale-applied) endpoints per particle. */
	TArray<FVector> CachedStarts;
	TArray<FVector> CachedEnds;

	float MaxRadius = 0.f;

	/** Rebuild the mesh section, drawing each particle Start->clamped end. */
	void RebuildSection(float FrontRadius);

	/** Build a cylinder mesh section from Start to End with given Radius and NumSides. */
	static void BuildCylinder(
		const FVector& Start, const FVector& End, float Radius, int32 NumSides,
		TArray<FVector>& OutVerts, TArray<int32>& OutTris,
		TArray<FVector>& OutNormals, TArray<FVector2D>& OutUVs,
		TArray<FColor>& OutColors);
};
