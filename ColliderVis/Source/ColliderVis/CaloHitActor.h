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
 *
 * Supports propagation-time reveal: each hit "lights up" when the spherical
 * animation front (radius from the collision center) reaches it. Hidden hits
 * are collapsed to zero scale via Custom Primitive Data[1] (lit flag) and an
 * instance-scale toggle so they are invisible until reached.
 */
UCLASS()
class COLLIDERVIS_API ACaloHitActor : public AActor
{
	GENERATED_BODY()

public:
	ACaloHitActor();

	/** Populate instances from a filtered subset of calo hits (same collection). */
	void SetHits(const TArray<FEDMCaloHit>& Hits, const UEventDisplayConfig* Cfg);

	/** Largest hit radius from origin (UE cm) — for the manager's front sizing. */
	float GetMaxHitRadius() const { return MaxHitRadius; }

	/**
	 * Light up every hit whose radius from the collision center is <= FrontRadius.
	 * Idempotent; safe to call every tick.
	 */
	void SetRevealRadius(float FrontRadius);

	/** Light up all hits instantly (final state). */
	void RevealAll();

	/** Hide all hits (animation start state). */
	void HideAll();

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY(VisibleAnywhere)
	UInstancedStaticMeshComponent* ISMC;

	/** Per-instance radius from collision center (UE cm), index-aligned to ISMC. */
	TArray<float> HitRadii;

	/** Per-instance full transform when lit (so we can collapse/restore scale). */
	TArray<FTransform> HitTransforms;

	float MaxHitRadius = 0.f;
};
