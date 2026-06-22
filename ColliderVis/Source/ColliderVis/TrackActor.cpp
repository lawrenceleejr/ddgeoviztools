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

	// --- Velocity fraction beta = v/c for propagation-time reveal ---
	// beta = p / E, E = sqrt(p^2 + m^2). We have no per-track mass, so we
	// approximate with a charged-pion-like rest mass; this keeps high-momentum
	// tracks at beta ~ 1 while low-momentum tracks emerge a bit slower.
	{
		const float MassGeV = 0.1396f; // ~charged pion; pure visualization heuristic
		const float P = FMath::Max(Track.MomentumGeV, 0.f);
		const float E = FMath::Sqrt(P * P + MassGeV * MassGeV);
		Beta = (E > KINDA_SMALL_NUMBER) ? FMath::Clamp(P / E, 0.05f, 1.f) : 1.f;
	}

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

	// Create one SplineMeshComponent per segment, tracking cumulative arc length
	const int32 NumPoints = Spline->GetNumberOfSplinePoints();
	SegmentEndArcLength.Reset();
	TotalArcLength = 0.f;
	for (int32 i = 0; i < NumPoints - 1; ++i)
	{
		AddSegment(i, CylinderMesh, DynMat, Cfg->TrackTubeRadius);

		const FVector A = Spline->GetLocationAtSplinePoint(i,     ESplineCoordinateSpace::Local);
		const FVector B = Spline->GetLocationAtSplinePoint(i + 1, ESplineCoordinateSpace::Local);
		TotalArcLength += FVector::Dist(A, B);
		SegmentEndArcLength.Add(TotalArcLength);
	}
}

void ATrackActor::SetRevealArcLength(float RevealS)
{
	// Show every segment whose START arc length is within the reveal front.
	// SegmentEndArcLength[i] is the arc length at the END of segment i, so
	// the start of segment i is SegmentEndArcLength[i-1] (0 for i==0).
	for (int32 i = 0; i < SegmentMeshes.Num(); ++i)
	{
		if (!SegmentMeshes[i]) continue;
		const float SegStart = (i == 0) ? 0.f : SegmentEndArcLength[i - 1];
		const bool bVisible = SegStart <= RevealS;
		SegmentMeshes[i]->SetVisibility(bVisible);
	}
}

void ATrackActor::RevealAll()
{
	for (USplineMeshComponent* SMC : SegmentMeshes)
	{
		if (SMC) SMC->SetVisibility(true);
	}
}

void ATrackActor::HideAll()
{
	for (USplineMeshComponent* SMC : SegmentMeshes)
	{
		if (SMC) SMC->SetVisibility(false);
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

	// Uniform thin tube: the track is just a curve tracing the trajectory — no
	// taper (the old start/end taper ballooned into cones once TubeRadius got
	// small, and represented nothing physical).
	SMC->SetStartScale(FVector2D(TubeRadius, TubeRadius));
	SMC->SetEndScale(FVector2D(TubeRadius, TubeRadius));

	// Set spline positions and tangents
	FVector StartPos, StartTangent, EndPos, EndTangent;
	Spline->GetLocationAndTangentAtSplinePoint(Idx,     StartPos,   StartTangent, ESplineCoordinateSpace::Local);
	Spline->GetLocationAndTangentAtSplinePoint(Idx + 1, EndPos,     EndTangent,   ESplineCoordinateSpace::Local);

	SMC->SetStartAndEnd(StartPos, StartTangent, EndPos, EndTangent);
	SMC->AttachToComponent(Spline, FAttachmentTransformRules::KeepRelativeTransform);

	SegmentMeshes.Add(SMC);
}
