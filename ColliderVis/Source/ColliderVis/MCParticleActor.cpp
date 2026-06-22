#include "MCParticleActor.h"
#include "EventDisplayConfig.h"
#include "ProceduralMeshComponent.h"
#include "Materials/MaterialInstanceDynamic.h"

AMCParticleActor::AMCParticleActor()
{
	PrimaryActorTick.bCanEverTick = false;

	LineMesh = CreateDefaultSubobject<UProceduralMeshComponent>(TEXT("LineMesh"));
	RootComponent = LineMesh;
}

void AMCParticleActor::BeginPlay()
{
	Super::BeginPlay();
}

void AMCParticleActor::SetParticles(const TArray<FEDMMCParticle>& Particles, const UEventDisplayConfig* Cfg)
{
	if (!Cfg) return;

	LineMesh->ClearAllMeshSections();
	CachedStarts.Reset();
	CachedEnds.Reset();
	MaxRadius = 0.f;

	if (!Cfg->bShowMCParticles) return;

	const float Scale = Cfg->WorldScale;

	for (const FEDMMCParticle& P : Particles)
	{
		const FVector Start = P.Vertex    * Scale;
		const FVector End   = P.EndVertex * Scale;
		if (FVector::Dist(Start, End) < 1.f) continue;  // skip zero-length

		CachedStarts.Add(Start);
		CachedEnds.Add(End);
		MaxRadius = FMath::Max(MaxRadius, End.Size());
	}

	// Default to fully drawn (final state); the animation will call HideAll first.
	RebuildSection(TNumericLimits<float>::Max());
}

void AMCParticleActor::SetRevealRadius(float FrontRadius)
{
	RebuildSection(FrontRadius);
}

void AMCParticleActor::RevealAll()
{
	RebuildSection(TNumericLimits<float>::Max());
}

void AMCParticleActor::HideAll()
{
	RebuildSection(0.f);
}

void AMCParticleActor::RebuildSection(float FrontRadius)
{
	LineMesh->ClearAllMeshSections();

	const float Radius = 1.0f;   // 1 cm tube radius
	const int32 Sides  = 8;

	TArray<FVector>    AllVerts;
	TArray<int32>      AllTris;
	TArray<FVector>    AllNormals;
	TArray<FVector2D>  AllUVs;
	TArray<FColor>     AllColors;

	for (int32 i = 0; i < CachedStarts.Num(); ++i)
	{
		const FVector Start = CachedStarts[i];
		const FVector End   = CachedEnds[i];

		// Clamp the drawn end to the spherical front: grow from Start toward End
		// until we cross FrontRadius. We march along the segment and find the
		// fraction at which |Start + f*(End-Start)| == FrontRadius (approx via
		// parametric clamp on the endpoint radius for simplicity & robustness).
		FVector DrawEnd = End;
		const float StartR = Start.Size();
		const float EndR   = End.Size();

		if (FrontRadius <= StartR)
		{
			continue; // front has not reached this line's start yet
		}
		if (FrontRadius < EndR && EndR > StartR + KINDA_SMALL_NUMBER)
		{
			// Linear interpolation on radius along the segment (good enough for
			// near-radial truth lines emanating from the vertex region).
			const float Frac = FMath::Clamp((FrontRadius - StartR) / (EndR - StartR), 0.f, 1.f);
			DrawEnd = Start + (End - Start) * Frac;
		}

		if (FVector::Dist(Start, DrawEnd) < 1.f) continue;

		const int32 BaseIdx = AllVerts.Num();

		TArray<FVector>   V; TArray<int32>   T;
		TArray<FVector>   N; TArray<FVector2D> UV;
		TArray<FColor>    C;
		BuildCylinder(Start, DrawEnd, Radius, Sides, V, T, N, UV, C);

		for (int32& Tri : T) Tri += BaseIdx;

		AllVerts   .Append(V);
		AllTris    .Append(T);
		AllNormals .Append(N);
		AllUVs     .Append(UV);
		AllColors  .Append(C);
	}

	if (AllVerts.Num() > 0)
	{
		LineMesh->CreateMeshSection(0, AllVerts, AllTris, AllNormals,
		                            AllUVs, AllColors, TArray<FProcMeshTangent>(), false);

		UMaterialInterface* Mat = LoadObject<UMaterialInterface>(
			nullptr, TEXT("/Game/Materials/M_MCParticle.M_MCParticle"));
		if (Mat) LineMesh->SetMaterial(0, Mat);
	}
}

void AMCParticleActor::BuildCylinder(
	const FVector& Start, const FVector& End, float Radius, int32 NumSides,
	TArray<FVector>& OutVerts, TArray<int32>& OutTris,
	TArray<FVector>& OutNormals, TArray<FVector2D>& OutUVs,
	TArray<FColor>& OutColors)
{
	const FVector Dir    = (End - Start).GetSafeNormal();
	const float   Length = FVector::Dist(Start, End);

	// Build an orthonormal basis around Dir
	FVector BasisX, BasisY;
	Dir.FindBestAxisVectors(BasisX, BasisY);

	// Generate ring vertices at both caps
	for (int32 Cap = 0; Cap < 2; ++Cap)
	{
		const FVector CentrePt = Cap == 0 ? Start : End;
		for (int32 s = 0; s < NumSides; ++s)
		{
			const float Angle = 2.f * PI * s / NumSides;
			const FVector Offset = (FMath::Cos(Angle) * BasisX + FMath::Sin(Angle) * BasisY) * Radius;
			OutVerts.Add(CentrePt + Offset);
			OutNormals.Add(Offset.GetSafeNormal());
			OutUVs.Add(FVector2D((float)s / NumSides, (float)Cap));
			OutColors.Add(FColor(200, 200, 255, 200));
		}
	}

	// Quads connecting the two rings
	for (int32 s = 0; s < NumSides; ++s)
	{
		const int32 s1 = (s + 1) % NumSides;
		const int32 A = s;
		const int32 B = s1;
		const int32 C = NumSides + s;
		const int32 D = NumSides + s1;

		// Two triangles per quad
		OutTris.Append({ A, C, B });
		OutTris.Append({ B, C, D });
	}
}
