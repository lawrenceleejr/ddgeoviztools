#include "TrackActor.h"
#include "EventDisplayConfig.h"
#include "Components/SplineComponent.h"
#include "Components/SplineMeshComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "UObject/ConstructorHelpers.h"

ATrackActor::ATrackActor()
{
	PrimaryActorTick.bCanEverTick = false;

	Spline = CreateDefaultSubobject<USplineComponent>(TEXT("Spline"));
	RootComponent = Spline;
	Spline->ClearSplinePoints(false);
}

void ATrackActor::BeginPlay()
{
	Super::BeginPlay();
}

void ATrackActor::SetTrackData(const FEDMTrack& Track, const UEventDisplayConfig* Cfg)
{
	if (!Cfg || Track.Points.Num() < 2) return;

	const float Scale = Cfg->WorldScale;   // mm → cm

	// Choose color by charge
	FLinearColor TrackColor;
	if      (Track.Charge > 0.f) TrackColor = Cfg->PositiveTrackColor;
	else if (Track.Charge < 0.f) TrackColor = Cfg->NegativeTrackColor;
	else                          TrackColor = Cfg->NeutralTrackColor;

	// Emissive intensity proportional to momentum
	const float EmissiveIntensity = FMath::Clamp(Track.MomentumGeV * Cfg->EnergyEmissiveScale, 0.f, 1000.f);

	// Build spline
	Spline->ClearSplinePoints(false);
	for (const FVector& Pt : Track.Points)
	{
		Spline->AddSplinePoint(Pt * Scale, ESplineCoordinateSpace::World, false);
	}
	Spline->UpdateSpline();

	// Load a 1m cylinder static mesh (unit cylinder, scaled per segment)
	UStaticMesh* CylinderMesh = LoadObject<UStaticMesh>(
		nullptr, TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));

	// Load M_Track material
	UMaterialInterface* BaseMat = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Game/Materials/M_Track.M_Track"));

	UMaterialInstanceDynamic* DynMat = nullptr;
	if (BaseMat)
	{
		DynMat = UMaterialInstanceDynamic::Create(BaseMat, this);
		DynMat->SetVectorParameterValue(TEXT("TrackColor"), TrackColor);
		DynMat->SetScalarParameterValue(TEXT("EmissiveIntensity"), EmissiveIntensity);
	}

	// Create one SplineMeshComponent per segment
	const int32 NumPoints = Spline->GetNumberOfSplinePoints();
	for (int32 i = 0; i < NumPoints - 1; ++i)
	{
		AddSegment(i, CylinderMesh, DynMat, Cfg->TrackTubeRadius);
	}
}

void ATrackActor::AddSegment(int32 Idx, UStaticMesh* CylinderMesh,
                              UMaterialInterface* MatInst, float TubeRadius)
{
	USplineMeshComponent* SMC = NewObject<USplineMeshComponent>(
		this, USplineMeshComponent::StaticClass(),
		*FString::Printf(TEXT("Seg_%d"), Idx));
	SMC->SetMobility(EComponentMobility::Movable);
	SMC->SetStaticMesh(CylinderMesh);
	SMC->SetForwardAxis(ESplineMeshAxis::Z);
	SMC->RegisterComponent();

	if (MatInst)
	{
		SMC->SetMaterial(0, MatInst);
	}

	// Taper: full radius at start, diminished at end for energy dissipation look
	const float EndRadius = FMath::Max(TubeRadius * 0.6f, 0.5f);
	SMC->SetStartScale(FVector2D(TubeRadius, TubeRadius));
	SMC->SetEndScale(FVector2D(EndRadius, EndRadius));

	// Set spline positions and tangents
	FVector StartPos, StartTangent, EndPos, EndTangent;
	Spline->GetLocationAndTangentAtSplinePoint(Idx,     StartPos,   StartTangent, ESplineCoordinateSpace::Local);
	Spline->GetLocationAndTangentAtSplinePoint(Idx + 1, EndPos,     EndTangent,   ESplineCoordinateSpace::Local);

	SMC->SetStartAndEnd(StartPos, StartTangent, EndPos, EndTangent);
	SMC->AttachToComponent(Spline, FAttachmentTransformRules::KeepRelativeTransform);

	SegmentMeshes.Add(SMC);
}
