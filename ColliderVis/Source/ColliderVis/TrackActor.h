#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "EDM4HEPTypes.h"
#include "TrackActor.generated.h"

class USplineComponent;
class USplineMeshComponent;
class UEventDisplayConfig;

/**
 * Renders one reconstructed charged track as a spline tube with
 * energy-proportional emissive glow.
 *
 * Supports propagation-time reveal: the track is parametrized by arc length
 * from the collision vertex and progressively unhidden up to a reveal arc
 * length s = beta * c * t (see SetRevealArcLength). Charged tracks curve, so
 * the reveal follows the stored trajectory points exactly.
 */
UCLASS()
class COLLIDERVIS_API ATrackActor : public AActor
{
	GENERATED_BODY()

public:
	ATrackActor();

	/**
	 * Build the spline geometry and assign materials.
	 * Call immediately after spawning, before registering components.
	 */
	void SetTrackData(const FEDMTrack& Track, const UEventDisplayConfig* Cfg);

	/** Total arc length of the track (UE cm), measured from the first point. */
	float GetTotalArcLength() const { return TotalArcLength; }

	/**
	 * Velocity fraction beta = v/c for this track, used to convert animation
	 * time to revealed arc length. Derived from momentum (defaults to ~1).
	 */
	float GetBeta() const { return Beta; }

	/**
	 * Reveal the track up to the given arc length (UE cm) from the vertex.
	 * Segments fully before RevealS are shown; segments past it are hidden;
	 * the straddling segment is shown (cheap partial reveal). Idempotent.
	 */
	void SetRevealArcLength(float RevealS);

	/** Reveal the whole track instantly (final state). */
	void RevealAll();

	/** Hide the entire track (animation start state). */
	void HideAll();

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY(VisibleAnywhere)
	USplineComponent* Spline;

	UPROPERTY()
	TArray<USplineMeshComponent*> SegmentMeshes;

	/** Cumulative arc length at the END of each segment (UE cm). */
	TArray<float> SegmentEndArcLength;

	float TotalArcLength = 0.f;
	float Beta = 1.f;

	/** Build one USplineMeshComponent segment between points [Idx] and [Idx+1] */
	void AddSegment(int32 Idx, UStaticMesh* CylinderMesh,
	                UMaterialInterface* MatInst, float TubeRadius);
};
