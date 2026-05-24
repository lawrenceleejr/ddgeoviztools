#include "EventDisplayManager.h"
#include "EventDisplayConfig.h"
#include "EDM4HEPReader.h"
#include "TrackActor.h"
#include "CaloHitActor.h"
#include "MCParticleActor.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/Paths.h"
#include "Misc/Guid.h"

AEventDisplayManager::AEventDisplayManager()
{
	PrimaryActorTick.bCanEverTick = false;
}

void AEventDisplayManager::BeginPlay()
{
	Super::BeginPlay();
}

bool AEventDisplayManager::LoadEDM4HEPFile(const FString& Path)
{
	if (!Config)
	{
		UE_LOG(LogTemp, Error, TEXT("EventDisplayManager: Config is null — assign DA_EventDisplayConfig"));
		return false;
	}

	CurrentFilePath = Path;
	CurrentEventIndex = -1;
	EventFiles.Reset();

	// Unique temp dir per load to avoid stale files
	ConvertedOutputDir = FPaths::ProjectSavedDir() /
	                     TEXT("EDM4HEP") /
	                     FGuid::NewGuid().ToString();
	IFileManager::Get().MakeDirectory(*ConvertedOutputDir, true);

	if (!RunPythonConverter(Path, ConvertedOutputDir))
	{
		UE_LOG(LogTemp, Error, TEXT("EventDisplayManager: Python conversion failed for '%s'"), *Path);
		return false;
	}

	// Discover event JSON files
	TArray<FString> FoundFiles;
	IFileManager::Get().FindFiles(FoundFiles, *(ConvertedOutputDir / TEXT("event_*.json")), true, false);
	FoundFiles.Sort();

	for (const FString& F : FoundFiles)
	{
		EventFiles.Add(ConvertedOutputDir / F);
	}

	TotalEvents = EventFiles.Num();
	UE_LOG(LogTemp, Log, TEXT("EventDisplayManager: Found %d events"), TotalEvents);

	if (TotalEvents > 0)
	{
		LoadEvent(0);
	}

	return TotalEvents > 0;
}

void AEventDisplayManager::LoadNextEvent()
{
	if (TotalEvents == 0) return;
	LoadEvent((CurrentEventIndex + 1) % TotalEvents);
}

void AEventDisplayManager::LoadEvent(int32 Index)
{
	if (!Config || !EventFiles.IsValidIndex(Index)) return;

	FEDMEvent Event;
	if (!UEDMReader::ParseEventJSON(EventFiles[Index], Event))
	{
		UE_LOG(LogTemp, Warning, TEXT("EventDisplayManager: Failed to parse event %d"), Index);
		return;
	}

	CurrentEventIndex = Index;
	ClearEventActors();
	SpawnEventActors(Event);

	OnEventLoaded.Broadcast(Index);
}

FVector AEventDisplayManager::GetEventCentroid() const
{
	FVector Sum = FVector::ZeroVector;
	int32 Count = 0;

	for (const ATrackActor* A : TrackActors)
	{
		if (A) { Sum += A->GetActorLocation(); Count++; }
	}
	for (const ACaloHitActor* A : CaloHitActors)
	{
		if (A) { Sum += A->GetActorLocation(); Count++; }
	}

	return Count > 0 ? Sum / Count : GetActorLocation();
}

void AEventDisplayManager::ClearEventActors()
{
	for (ATrackActor* A     : TrackActors)     { if (A) A->Destroy(); }
	for (ACaloHitActor* A   : CaloHitActors)   { if (A) A->Destroy(); }
	for (AMCParticleActor* A: MCParticleActors){ if (A) A->Destroy(); }

	TrackActors    .Reset();
	CaloHitActors  .Reset();
	MCParticleActors.Reset();
}

void AEventDisplayManager::SpawnEventActors(const FEDMEvent& Event)
{
	UWorld* World = GetWorld();
	if (!World) return;

	// --- Tracks ---
	if (Config->bShowTracks)
	{
		for (const FEDMTrack& Track : Event.Tracks)
		{
			ATrackActor* Actor = World->SpawnActor<ATrackActor>();
			if (Actor)
			{
				Actor->SetTrackData(Track, Config);
				TrackActors.Add(Actor);
			}
		}
	}

	// --- Calo Hits — group by collection ---
	TMap<FString, TArray<FEDMCaloHit>> HitsByCollection;
	for (const FEDMCaloHit& Hit : Event.CaloHits)
	{
		// Filter to enabled collections
		bool bEnabled = Config->EnabledCaloCollections.Contains(FName(Hit.CollectionName));
		if (bEnabled)
		{
			HitsByCollection.FindOrAdd(Hit.CollectionName).Add(Hit);
		}
	}

	for (auto& KV : HitsByCollection)
	{
		ACaloHitActor* Actor = World->SpawnActor<ACaloHitActor>();
		if (Actor)
		{
			Actor->SetHits(KV.Value, Config);
			CaloHitActors.Add(Actor);
		}
	}

	// --- MC Particles ---
	AMCParticleActor* MCPActor = World->SpawnActor<AMCParticleActor>();
	if (MCPActor)
	{
		MCPActor->SetParticles(Event.MCParticles, Config);
		MCParticleActors.Add(MCPActor);
	}
}

bool AEventDisplayManager::RunPythonConverter(const FString& InputPath, const FString& OutputDir)
{
	if (!Config) return false;

	const FString Script = Config->EDM4HEPScriptPath;
	if (Script.IsEmpty())
	{
		UE_LOG(LogTemp, Warning, TEXT("EventDisplayManager: EDM4HEPScriptPath not set in Config"));
		return false;
	}

	const FString Args = FString::Printf(TEXT("\"%s\" \"%s\" \"%s\""),
	                                      *Script, *InputPath, *OutputDir);

	FProcHandle Proc = FPlatformProcess::CreateProc(
		*Config->PythonExecutable,
		*Args,
		/*bLaunchDetached=*/true,
		/*bLaunchHidden=*/true,
		/*bLaunchReallyHidden=*/true,
		nullptr, 0, nullptr, nullptr);

	if (!Proc.IsValid())
	{
		UE_LOG(LogTemp, Error, TEXT("EventDisplayManager: Failed to launch Python process"));
		return false;
	}

	// Block until conversion finishes (typically < 30s for small files)
	FPlatformProcess::WaitForProc(Proc);

	int32 ReturnCode = -1;
	FPlatformProcess::GetProcReturnCode(Proc, &ReturnCode);
	FPlatformProcess::CloseProc(Proc);

	return ReturnCode == 0;
}
