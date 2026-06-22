#include "CaloHitActor.h"
#include "EventDisplayConfig.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Materials/MaterialInstanceDynamic.h"

ACaloHitActor::ACaloHitActor()
{
	PrimaryActorTick.bCanEverTick = false;

	ISMC = CreateDefaultSubobject<UInstancedStaticMeshComponent>(TEXT("ISMC"));
	RootComponent = ISMC;
	ISMC->NumCustomDataFloats = 2;   // [0] = normalised energy, [1] = lit flag (0/1)
}

void ACaloHitActor::BeginPlay()
{
	Super::BeginPlay();
}

void ACaloHitActor::SetHits(const TArray<FEDMCaloHit>& Hits, const UEventDisplayConfig* Cfg)
{
	if (!Cfg || Hits.IsEmpty()) return;

	ISMC->ClearInstances();
	HitRadii.Reset();
	HitTransforms.Reset();
	MaxHitRadius = 0.f;

	// Load cube mesh
	UStaticMesh* CubeMesh = LoadObject<UStaticMesh>(
		nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	ISMC->SetStaticMesh(CubeMesh);

	// Load material
	UMaterialInterface* BaseMat = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Game/Materials/M_CaloHit.M_CaloHit"));
	if (BaseMat)
	{
		ISMC->SetMaterial(0, BaseMat);
	}

	const float Scale  = Cfg->WorldScale;       // mm → cm
	const float HalfSz = Cfg->CaloHitBaseSize;  // base cube half-size in cm

	// Find max energy for normalisation
	float MaxEnergy = 0.f;
	for (const FEDMCaloHit& H : Hits)
	{
		MaxEnergy = FMath::Max(MaxEnergy, H.EnergyGeV);
	}
	if (MaxEnergy <= 0.f) MaxEnergy = 1.f;

	for (int32 i = 0; i < Hits.Num(); ++i)
	{
		const FEDMCaloHit& H = Hits[i];

		// Scale cube size by sqrt(energy) for perceptual linearity
		const float EnNorm    = H.EnergyGeV / MaxEnergy;
		const float SizeScale = FMath::Lerp(0.3f, 1.0f, FMath::Sqrt(EnNorm));
		const float CubeSize  = HalfSz * SizeScale * 2.f;  // full side in cm

		FTransform T;
		const FVector WorldPos = H.Position * Scale;
		T.SetLocation(WorldPos);
		T.SetScale3D(FVector(CubeSize / 100.f));   // Engine cube is 100cm default

		int32 Idx = ISMC->AddInstance(T);
		// Custom Primitive Data[0] drives emissive in M_CaloHit shader
		ISMC->SetCustomDataValue(Idx, 0, EnNorm);
		ISMC->SetCustomDataValue(Idx, 1, 1.f); // lit by default (final state)

		HitTransforms.Add(T);
		// Radius from the collision center (world origin / detector center).
		const float Radius = WorldPos.Size();
		HitRadii.Add(Radius);
		MaxHitRadius = FMath::Max(MaxHitRadius, Radius);
	}

	ISMC->MarkRenderStateDirty();
}

void ACaloHitActor::SetRevealRadius(float FrontRadius)
{
	for (int32 i = 0; i < HitRadii.Num(); ++i)
	{
		const bool bLit = HitRadii[i] <= FrontRadius;
		// Collapse unlit instances to zero scale so they are fully invisible,
		// restore the stored transform when the front reaches them.
		if (bLit)
		{
			ISMC->UpdateInstanceTransform(i, HitTransforms[i], /*bWorldSpace*/false, /*bMarkDirty*/false, /*bTeleport*/true);
		}
		else
		{
			FTransform Hidden = HitTransforms[i];
			Hidden.SetScale3D(FVector::ZeroVector);
			ISMC->UpdateInstanceTransform(i, Hidden, false, false, true);
		}
		ISMC->SetCustomDataValue(i, 1, bLit ? 1.f : 0.f, /*bMarkRenderStateDirty*/false);
	}
	ISMC->MarkRenderStateDirty();
}

void ACaloHitActor::RevealAll()
{
	for (int32 i = 0; i < HitTransforms.Num(); ++i)
	{
		ISMC->UpdateInstanceTransform(i, HitTransforms[i], false, false, true);
		ISMC->SetCustomDataValue(i, 1, 1.f, false);
	}
	ISMC->MarkRenderStateDirty();
}

void ACaloHitActor::HideAll()
{
	for (int32 i = 0; i < HitTransforms.Num(); ++i)
	{
		FTransform Hidden = HitTransforms[i];
		Hidden.SetScale3D(FVector::ZeroVector);
		ISMC->UpdateInstanceTransform(i, Hidden, false, false, true);
		ISMC->SetCustomDataValue(i, 1, 0.f, false);
	}
	ISMC->MarkRenderStateDirty();
}
