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

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY(VisibleAnywhere)
	USplineComponent* Spline;

	UPROPERTY()
	TArray<USplineMeshComponent*> SegmentMeshes;

	/** Build one USplineMeshComponent segment between points [Idx] and [Idx+1] */
	void AddSegment(int32 Idx, UStaticMesh* CylinderMesh,
	                UMaterialInterface* MatInst, float TubeRadius);
};
