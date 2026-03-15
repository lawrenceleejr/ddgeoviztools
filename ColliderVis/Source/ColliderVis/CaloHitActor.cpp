#include "CaloHitActor.h"
#include "EventDisplayConfig.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Materials/MaterialInstanceDynamic.h"

ACaloHitActor::ACaloHitActor()
{
	PrimaryActorTick.bCanEverTick = false;

	ISMC = CreateDefaultSubobject<UInstancedStaticMeshComponent>(TEXT("ISMC"));
	RootComponent = ISMC;
	ISMC->NumCustomDataFloats = 1;   // Custom Primitive Data[0] = normalised energy
}

void ACaloHitActor::BeginPlay()
{
	Super::BeginPlay();
}

void ACaloHitActor::SetHits(const TArray<FEDMCaloHit>& Hits, const UEventDisplayConfig* Cfg)
{
	if (!Cfg || Hits.IsEmpty()) return;

	ISMC->ClearInstances();

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
		T.SetLocation(H.Position * Scale);
		T.SetScale3D(FVector(CubeSize / 100.f));   // Engine cube is 100cm default

		int32 Idx = ISMC->AddInstance(T);
		// Custom Primitive Data[0] drives emissive in M_CaloHit shader
		ISMC->SetCustomDataValue(Idx, 0, EnNorm);
	}

	ISMC->MarkRenderStateDirty();
}
