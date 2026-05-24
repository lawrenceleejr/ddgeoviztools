#pragma once

#include "CoreMinimal.h"
#include "EDM4HEPTypes.h"
#include "EDM4HEPReader.generated.h"

/**
 * Stateless utility class for deserialising event JSON files produced by
 * Tools/edm4hep_to_json.py into FEDMEvent structs.
 */
UCLASS(BlueprintType)
class COLLIDERVIS_API UEDMReader : public UObject
{
	GENERATED_BODY()

public:
	/**
	 * Parse a single event_NNNN.json file.
	 * @param FilePath  Absolute path to the JSON file.
	 * @param OutEvent  Receives the parsed event data.
	 * @return true on success, false on file/parse error.
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|EDM4HEP")
	static bool ParseEventJSON(const FString& FilePath, FEDMEvent& OutEvent);
};
