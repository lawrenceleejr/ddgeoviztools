#include "DetectorVisibilityManager.h"
#include "Components/PrimitiveComponent.h"
#include "EngineUtils.h"

ADetectorVisibilityManager::ADetectorVisibilityManager()
{
	PrimaryActorTick.bCanEverTick = false;
}

void ADetectorVisibilityManager::BeginPlay()
{
	Super::BeginPlay();
	RebuildActorCache();

	// Apply default visibility from config
	if (Config)
	{
		for (const FSubDetectorEntry& Entry : Config->SubDetectors)
		{
			VisibilityState.Add(Entry.Name, Entry.bVisibleByDefault);
			if (!Entry.bVisibleByDefault)
			{
				SetSubDetectorVisible(Entry.Name, false);
			}
		}
	}
}

void ADetectorVisibilityManager::RebuildActorCache()
{
	SubDetectorActors.Reset();

	if (!Config) return;

	// Build a lookup: tag → sub-detector name
	TMap<FName, FName> TagToName;
	for (const FSubDetectorEntry& Entry : Config->SubDetectors)
	{
		for (const FName& Tag : Entry.ActorTags)
		{
			TagToName.Add(Tag, Entry.Name);
		}
	}

	// Iterate all actors in the world
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		AActor* Actor = *It;
		for (const FName& Tag : Actor->Tags)
		{
			if (const FName* SDName = TagToName.Find(Tag))
			{
				SubDetectorActors.FindOrAdd(*SDName).Add(Actor);
				break;  // each actor belongs to at most one sub-detector
			}
		}
	}
}

void ADetectorVisibilityManager::SetSubDetectorVisible(FName Name, bool bVisible)
{
	VisibilityState.FindOrAdd(Name) = bVisible;

	TArray<AActor*>* Actors = SubDetectorActors.Find(Name);
	if (!Actors) return;

	for (AActor* Actor : *Actors)
	{
		if (Actor) ApplyVisibility(Actor, bVisible);
	}
}

void ADetectorVisibilityManager::ToggleSubDetector(FName Name)
{
	const bool bCurrent = IsSubDetectorVisible(Name);
	SetSubDetectorVisible(Name, !bCurrent);
}

void ADetectorVisibilityManager::SetAllVisible(bool bVisible)
{
	if (!Config) return;
	for (const FSubDetectorEntry& Entry : Config->SubDetectors)
	{
		SetSubDetectorVisible(Entry.Name, bVisible);
	}
}

bool ADetectorVisibilityManager::IsSubDetectorVisible(FName Name) const
{
	const bool* State = VisibilityState.Find(Name);
	return State ? *State : true;
}

void ADetectorVisibilityManager::ApplyVisibility(AActor* Actor, bool bVisible)
{
	if (!Actor) return;

	Actor->SetActorHiddenInGame(!bVisible);

	// Also toggle render state on each primitive component (handles ISMs)
	for (UActorComponent* Comp : Actor->GetComponents())
	{
		if (UPrimitiveComponent* PC = Cast<UPrimitiveComponent>(Comp))
		{
			PC->SetVisibility(bVisible, false);
		}
	}
}
