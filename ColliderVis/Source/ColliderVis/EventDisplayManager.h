#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "EDM4HEPTypes.h"
#include "EventDisplayManager.generated.h"

class UEventDisplayConfig;
class ATrackActor;
class ACaloHitActor;
class AMCParticleActor;
class USoundBase;
class UAudioComponent;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnEventLoaded, int32, EventIndex);

/**
 * Orchestrates EDM4HEP file conversion and event actor lifecycle.
 * Place one instance in the level; assign Config data asset in the Details panel.
 */
UCLASS(BlueprintType)
class COLLIDERVIS_API AEventDisplayManager : public AActor
{
	GENERATED_BODY()

public:
	AEventDisplayManager();

	/** Assigned in BP_EventDisplayManager Details panel */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Config")
	UEventDisplayConfig* Config;

	UPROPERTY(BlueprintReadOnly, Category = "State")
	FString CurrentFilePath;

	UPROPERTY(BlueprintReadOnly, Category = "State")
	int32 CurrentEventIndex = -1;

	UPROPERTY(BlueprintReadOnly, Category = "State")
	int32 TotalEvents = 0;

	/** Fired after a new event is displayed */
	UPROPERTY(BlueprintAssignable, Category = "Events")
	FOnEventLoaded OnEventLoaded;

	// --- Propagation animation tunables -------------------------------------

	/** Wall-clock duration (seconds) of the emergence animation, 0 -> full. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Animation", meta = (ClampMin = "0.05"))
	float EventAnimationDuration = 3.0f;

	/**
	 * Multiplier on how fast the spherical "speed-of-light" front sweeps the
	 * scene. The front reaches the farthest object exactly at the end of
	 * EventAnimationDuration when SpeedScale == 1; larger = faster.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Animation", meta = (ClampMin = "0.01"))
	float AnimationSpeedScale = 4.0f;

	/** If true, automatically play the emergence animation whenever an event loads. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Animation")
	bool bAnimateOnLoad = true;

	/** Sound cued when an event emerges (LMB / load). Soft ref; null = silent. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Audio")
	TSoftObjectPtr<USoundBase> EventSound;

	/** Resonant filter-sweep riser layered on each new event (the "resonance"). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Audio")
	TSoftObjectPtr<USoundBase> EventSweepSound;

	/** Big low impact "thud" played on each click / new event. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Audio")
	TSoftObjectPtr<USoundBase> ThudSound;

	/** On each new event, sweep a low-pass filter open across the ambience bed
	 *  (muffled -> bright) over this many seconds — a big "filter sweep" tied to the
	 *  collision. 0 disables it. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis|Audio")
	float EventFilterSweepDuration = 2.0f;

	// --- Public API ---------------------------------------------------------

	/**
	 * Run edm4hep_to_json.py on the given ROOT file, then load event 0.
	 * Blocks until conversion is complete.
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	bool LoadEDM4HEPFile(const FString& Path);

	/** Advance to the next event, wrapping around. (Static, no animation.) */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	void LoadNextEvent();

	/**
	 * Advance to the next event and play the propagation-time emergence
	 * animation. Called from the character on LMB.
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	void PlayNextEventAnimated();

	/** Play the emergence animation for the currently loaded event. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	void PlayAnimation();

	/** Load a specific event by index. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	void LoadEvent(int32 Index);

	/** Return world-space centroid of the current event's track/hit actors (for camera focus). */
	UFUNCTION(BlueprintPure, Category = "ColliderVis|EventDisplay")
	FVector GetEventCentroid() const;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	/** Sorted list of absolute paths to event_NNNN.json files */
	TArray<FString> EventFiles;

	/** Temp directory for JSON files from the last conversion */
	FString ConvertedOutputDir;

	UPROPERTY()
	TArray<ATrackActor*> TrackActors;

	UPROPERTY()
	TArray<ACaloHitActor*> CaloHitActors;

	UPROPERTY()
	TArray<AMCParticleActor*> MCParticleActors;

	// --- Animation state ----------------------------------------------------

	bool  bAnimating = false;
	float AnimElapsed = 0.f;

	// --- Audio filter sweep (fires on each new event) -----------------------
	/** The level ambience audio component (HallAmbience) whose low-pass filter we sweep. */
	UPROPERTY(Transient)
	TObjectPtr<UAudioComponent> AmbienceAudio;
	bool  bAudioSweeping = false;
	float SweepElapsed = 0.f;
	/** Kick off a low-pass filter sweep on the ambience bed. */
	void StartAudioSweep();
	/** Advance the active sweep; called every Tick. */
	void TickAudioSweep(float DeltaSeconds);

	/**
	 * The largest object radius (UE cm) from the collision center across the
	 * current event. The light-speed front travels this far over the duration.
	 */
	float MaxEventRadius = 0.f;

	void ClearEventActors();
	void SpawnEventActors(const FEDMEvent& Event);
	bool RunPythonConverter(const FString& InputPath, const FString& OutputDir);

	/** Discover & preload the bundled sample events in Content/Events/Samples. */
	void LoadSampleEvents();

	/** Populate EventFiles/TotalEvents from event_*.json files in Dir. Returns true if any found. */
	bool BuildEventListFromDir(const FString& Dir);

	/** Compute MaxEventRadius from spawned actors. */
	void ComputeMaxEventRadius();

	/** Apply the reveal state for a given normalized progress (0..1). */
	void ApplyAnimationProgress(float Alpha01);

	/** Snap the whole event to fully revealed. */
	void RevealEventInstant();
};
