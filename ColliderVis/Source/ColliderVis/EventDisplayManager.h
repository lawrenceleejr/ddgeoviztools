#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "EDM4HEPTypes.h"
#include "EventDisplayManager.generated.h"

class UEventDisplayConfig;
class ATrackActor;
class ACaloHitActor;
class AMCParticleActor;

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

	/**
	 * Run edm4hep_to_json.py on the given ROOT file, then load event 0.
	 * Blocks until conversion is complete.
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	void LoadEDM4HEPFile(const FString& Path);

	/** Advance to the next event, wrapping around. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	void LoadNextEvent();

	/** Load a specific event by index. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EventDisplay")
	void LoadEvent(int32 Index);

	/** Return world-space centroid of the current event's track/hit actors (for camera focus). */
	UFUNCTION(BlueprintPure, Category = "ColliderVis|EventDisplay")
	FVector GetEventCentroid() const;

protected:
	virtual void BeginPlay() override;

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

	void ClearEventActors();
	void SpawnEventActors(const FEDMEvent& Event);
	bool RunPythonConverter(const FString& InputPath, const FString& OutputDir);
};
