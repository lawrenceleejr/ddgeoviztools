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
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundBase.h"
#include "Sound/AmbientSound.h"
#include "Components/AudioComponent.h"

AEventDisplayManager::AEventDisplayManager()
{
	PrimaryActorTick.bCanEverTick = true;

	// Default emergence SFX (CC0 whoosh). Instance/BP may override; null = silent.
	EventSound = TSoftObjectPtr<USoundBase>(
		FSoftObjectPath(TEXT("/Game/Audio/S_SplashWhoosh.S_SplashWhoosh")));
	EventSweepSound = TSoftObjectPtr<USoundBase>(
		FSoftObjectPath(TEXT("/Game/Audio/S_EventSweep.S_EventSweep")));
	ThudSound = TSoftObjectPtr<USoundBase>(
		FSoftObjectPath(TEXT("/Game/Audio/S_Thud.S_Thud")));
}

void AEventDisplayManager::BeginPlay()
{
	Super::BeginPlay();

	// Bulletproofing: the whole pipeline early-returns if Config is null (see
	// LoadEvent), which is exactly the "events don't fire at all" symptom when the
	// data asset isn't wired on the placed actor. Auto-load the project default so
	// playback works regardless of editor instance wiring.
	if (!Config)
	{
		Config = LoadObject<UEventDisplayConfig>(
			nullptr, TEXT("/Game/Data/DA_EventDisplayConfig.DA_EventDisplayConfig"));
		UE_LOG(LogTemp, Warning,
		       TEXT("EventDisplayManager: Config was unassigned; auto-loaded default %s"),
		       Config ? TEXT("OK") : TEXT("FAILED (asset missing)"));
	}

	// Preload bundled sample events so something is visible immediately, even
	// before the user browses to an EDM4HEP file. These ship in
	// Content/Events/Samples/event_NNNN.json and already use the JSON schema the
	// manager spawns from.
	if (TotalEvents == 0)
	{
		LoadSampleEvents();
	}

	// Cache the level ambience audio component (HallAmbience) so each new event can
	// sweep a low-pass filter across the bed (see StartAudioSweep).
	{
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(this, AAmbientSound::StaticClass(), Found);
		if (Found.Num() > 0)
		{
			if (AAmbientSound* Amb = Cast<AAmbientSound>(Found[0]))
			{
				AmbienceAudio = Amb->GetAudioComponent();
			}
		}
	}
}

void AEventDisplayManager::LoadSampleEvents()
{
	const FString SamplesDir = FPaths::ProjectContentDir() / TEXT("Events") / TEXT("Samples");

	if (BuildEventListFromDir(SamplesDir))
	{
		CurrentFilePath = SamplesDir;

		UE_LOG(LogTemp, Log, TEXT("EventDisplayManager: Preloaded %d sample events from '%s'"),
		       TotalEvents, *SamplesDir);

		// Load event 0 so geometry is ready/visible at startup. Honour the
		// bAnimateOnLoad config: if set, play the emergence animation; otherwise
		// reveal the event statically so it is immediately on screen.
		LoadEvent(0);
		if (bAnimateOnLoad)
		{
			PlayAnimation();
		}
		else
		{
			RevealEventInstant();
		}
	}
	else
	{
		UE_LOG(LogTemp, Warning,
		       TEXT("EventDisplayManager: No sample events found in '%s' — LMB will do nothing until a file is loaded"),
		       *SamplesDir);
	}
}

bool AEventDisplayManager::BuildEventListFromDir(const FString& Dir)
{
	EventFiles.Reset();
	CurrentEventIndex = -1;

	TArray<FString> FoundFiles;
	IFileManager::Get().FindFiles(FoundFiles, *(Dir / TEXT("event_*.json")), true, false);
	FoundFiles.Sort();

	for (const FString& F : FoundFiles)
	{
		EventFiles.Add(Dir / F);
	}

	TotalEvents = EventFiles.Num();
	return TotalEvents > 0;
}

void AEventDisplayManager::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	TickAudioSweep(DeltaSeconds);

	if (!bAnimating) return;

	const float Duration = FMath::Max(EventAnimationDuration, 0.05f);
	AnimElapsed += DeltaSeconds * FMath::Max(AnimationSpeedScale, 0.01f);

	const float Alpha = FMath::Clamp(AnimElapsed / Duration, 0.f, 1.f);
	ApplyAnimationProgress(Alpha);

	if (Alpha >= 1.f)
	{
		bAnimating = false;
		RevealEventInstant();
	}
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
	TotalEvents = 0;

	const FString Ext = FPaths::GetExtension(Path).ToLower();

	// --- Direct-JSON path -----------------------------------------------------
	// The Browse button may hand us either a single event_*.json file or a
	// directory already containing event_*.json files (e.g. the bundled
	// samples). No python conversion needed in that case.
	if (Ext == TEXT("json"))
	{
		EventFiles.Add(Path);
		TotalEvents = 1;
		UE_LOG(LogTemp, Log, TEXT("EventDisplayManager: Loaded JSON directly: '%s'"), *Path);
	}
	else if (Ext.IsEmpty() && IFileManager::Get().DirectoryExists(*Path))
	{
		BuildEventListFromDir(Path);
		UE_LOG(LogTemp, Log, TEXT("EventDisplayManager: Found %d events in directory '%s'"), TotalEvents, *Path);
	}
	else
	{
		// --- EDM4HEP .root path: convert via python → JSON --------------------
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

		BuildEventListFromDir(ConvertedOutputDir);
		UE_LOG(LogTemp, Log, TEXT("EventDisplayManager: Converted '%s' → %d events"), *Path, TotalEvents);
	}

	if (TotalEvents > 0)
	{
		LoadEvent(0);
		if (bAnimateOnLoad)
		{
			PlayAnimation();
		}
		else
		{
			RevealEventInstant();
		}
	}
	else
	{
		UE_LOG(LogTemp, Warning, TEXT("EventDisplayManager: No events loaded from '%s'"), *Path);
	}

	return TotalEvents > 0;
}

void AEventDisplayManager::LoadNextEvent()
{
	if (TotalEvents == 0) return;
	LoadEvent((CurrentEventIndex + 1) % TotalEvents);
}

void AEventDisplayManager::PlayNextEventAnimated()
{
	if (TotalEvents == 0)
	{
		UE_LOG(LogTemp, Warning,
		       TEXT("EventDisplayManager: PlayNextEventAnimated called but no events are loaded — nothing to show"));
		return;
	}

	// Reuse existing next-event logic, then play the emergence animation.
	const int32 NextIndex = (CurrentEventIndex + 1) % TotalEvents;
	UE_LOG(LogTemp, Log, TEXT("EventDisplayManager: PlayNextEventAnimated → event %d / %d"),
	       NextIndex, TotalEvents);

	// Cue the emergence SFX (null-safe). Played soft — it fires on every new event,
	// so keep it a subtle, mellow swell rather than a harsh repeated whoosh.
	if (USoundBase* Snd = EventSound.LoadSynchronous())
	{
		UGameplayStatics::PlaySound2D(this, Snd, /*VolumeMultiplier=*/0.35f);
	}
	// Big resonant filter-sweep riser + a low thud impact on the new collision.
	if (USoundBase* Sw = EventSweepSound.LoadSynchronous())
	{
		UGameplayStatics::PlaySound2D(this, Sw, /*VolumeMultiplier=*/0.6f);
	}
	if (USoundBase* Th = ThudSound.LoadSynchronous())
	{
		UGameplayStatics::PlaySound2D(this, Th, /*VolumeMultiplier=*/0.9f);
	}

	// Big filter sweep across the whole ambience bed, tied to the new collision.
	StartAudioSweep();

	LoadEvent(NextIndex);
	PlayAnimation();
}

void AEventDisplayManager::StartAudioSweep()
{
	if (EventFilterSweepDuration <= 0.f || !AmbienceAudio) return;
	bAudioSweeping = true;
	SweepElapsed = 0.f;
	AmbienceAudio->SetLowPassFilterEnabled(true);
	AmbienceAudio->SetLowPassFilterFrequency(120.f);   // start deeply muffled, then sweep wide open
}

void AEventDisplayManager::TickAudioSweep(float DeltaSeconds)
{
	if (!bAudioSweeping || !AmbienceAudio) return;
	SweepElapsed += DeltaSeconds;
	const float Dur = FMath::Max(EventFilterSweepDuration, 0.05f);
	const float A   = FMath::Clamp(SweepElapsed / Dur, 0.f, 1.f);
	// Ease, then sweep the cutoff exponentially 300 Hz -> 20 kHz (perceptually linear).
	const float E      = FMath::InterpEaseInOut(0.f, 1.f, A, 2.f);
	const float Cutoff = 120.f * FMath::Pow(22000.f / 120.f, E);   // wide sweep 120 Hz -> 22 kHz
	AmbienceAudio->SetLowPassFilterFrequency(Cutoff);
	if (A >= 1.f)
	{
		bAudioSweeping = false;
		AmbienceAudio->SetLowPassFilterEnabled(false);   // fully open again
	}
}

void AEventDisplayManager::PlayAnimation()
{
	ComputeMaxEventRadius();

	UE_LOG(LogTemp, Log, TEXT("EventDisplayManager: PlayAnimation — MaxEventRadius=%.1f cm"), MaxEventRadius);

	if (MaxEventRadius <= KINDA_SMALL_NUMBER)
	{
		// No measurable trajectory/hit radius to animate against (e.g. tracks
		// have no usable geometry). Falling back to RevealAll guarantees the
		// event is at least visible rather than left fully hidden by
		// ApplyAnimationProgress(0).
		UE_LOG(LogTemp, Warning,
		       TEXT("EventDisplayManager: MaxEventRadius ~0 — revealing event instantly so it is visible"));
		bAnimating = false;
		RevealEventInstant();
		return;
	}

	// Make sure the manager actually ticks so the front can sweep. If ticking is
	// disabled for any reason the animation would otherwise leave everything
	// hidden after ApplyAnimationProgress(0).
	SetActorTickEnabled(true);

	bAnimating = true;
	AnimElapsed = 0.f;
	ApplyAnimationProgress(0.f); // start fully hidden, Tick reveals over the duration
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
	bAnimating = false;
	ClearEventActors();
	SpawnEventActors(Event);

	UE_LOG(LogTemp, Log,
	       TEXT("EventDisplayManager: Loaded event %d/%d (file '%s') — spawned %d track(s), %d calo collection(s), %d MC actor(s); parsed %d tracks / %d calo hits / %d MC particles"),
	       Index, TotalEvents, *FPaths::GetCleanFilename(EventFiles[Index]),
	       TrackActors.Num(), CaloHitActors.Num(), MCParticleActors.Num(),
	       Event.Tracks.Num(), Event.CaloHits.Num(), Event.MCParticles.Num());

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

void AEventDisplayManager::ComputeMaxEventRadius()
{
	MaxEventRadius = 0.f;

	for (const ATrackActor* A : TrackActors)
	{
		if (A) MaxEventRadius = FMath::Max(MaxEventRadius, A->GetTotalArcLength());
	}
	for (const ACaloHitActor* A : CaloHitActors)
	{
		if (A) MaxEventRadius = FMath::Max(MaxEventRadius, A->GetMaxHitRadius());
	}
	for (const AMCParticleActor* A : MCParticleActors)
	{
		if (A) MaxEventRadius = FMath::Max(MaxEventRadius, A->GetMaxRadius());
	}
}

void AEventDisplayManager::ApplyAnimationProgress(float Alpha01)
{
	// The notional "speed-of-light" front travels MaxEventRadius over the full
	// duration, so its distance from the collision center at progress Alpha is:
	const float LightFront = MaxEventRadius * Alpha01;

	// Tracks: reveal arc length s = LightFront * beta. Slower (low-momentum)
	// particles cover less trajectory in the same propagation time, so they
	// lag behind the light front. Charged tracks curve, but we parametrize by
	// arc length along the stored trajectory points, so curvature is honoured.
	for (ATrackActor* A : TrackActors)
	{
		if (A) A->SetRevealArcLength(LightFront * A->GetBeta());
	}

	// Calo hits light up when the front (track front) reaches their radius.
	for (ACaloHitActor* A : CaloHitActors)
	{
		if (A) A->SetRevealRadius(LightFront);
	}

	// MC truth lines grow radially from the vertex with the light front.
	for (AMCParticleActor* A : MCParticleActors)
	{
		if (A) A->SetRevealRadius(LightFront);
	}
}

void AEventDisplayManager::RevealEventInstant()
{
	for (ATrackActor* A : TrackActors)        { if (A) A->RevealAll(); }
	for (ACaloHitActor* A : CaloHitActors)    { if (A) A->RevealAll(); }
	for (AMCParticleActor* A : MCParticleActors){ if (A) A->RevealAll(); }
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
