#include "EDM4HEPReader.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonSerializer.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

bool UEDMReader::ParseEventJSON(const FString& FilePath, FEDMEvent& OutEvent)
{
	OutEvent = FEDMEvent{};

	FString RawJson;
	if (!FFileHelper::LoadFileToString(RawJson, *FilePath))
	{
		UE_LOG(LogTemp, Warning, TEXT("EDM4HEPReader: failed to load file '%s'"), *FilePath);
		return false;
	}

	TSharedPtr<FJsonObject> Root;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(RawJson);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		UE_LOG(LogTemp, Warning, TEXT("EDM4HEPReader: JSON parse error in '%s'"), *FilePath);
		return false;
	}

	OutEvent.EventNumber = Root->GetIntegerField(TEXT("event_number"));
	OutEvent.RunNumber   = Root->GetIntegerField(TEXT("run_number"));

	// --- Tracks ---
	const TArray<TSharedPtr<FJsonValue>>* TracksArr;
	if (Root->TryGetArrayField(TEXT("tracks"), TracksArr))
	{
		for (const TSharedPtr<FJsonValue>& TrackVal : *TracksArr)
		{
			const TSharedPtr<FJsonObject>& TrackObj = TrackVal->AsObject();
			if (!TrackObj.IsValid()) continue;

			FEDMTrack Track;
			Track.Charge      = (float)TrackObj->GetNumberField(TEXT("charge"));
			Track.MomentumGeV = (float)TrackObj->GetNumberField(TEXT("momentum_gev"));
			Track.PDG         = TrackObj->GetIntegerField(TEXT("pdg"));

			const TArray<TSharedPtr<FJsonValue>>* PointsArr;
			if (TrackObj->TryGetArrayField(TEXT("points"), PointsArr))
			{
				for (const TSharedPtr<FJsonValue>& PtVal : *PointsArr)
				{
					const TArray<TSharedPtr<FJsonValue>>& Coords = PtVal->AsArray();
					if (Coords.Num() >= 3)
					{
						Track.Points.Add(FVector(
							(float)Coords[0]->AsNumber(),
							(float)Coords[1]->AsNumber(),
							(float)Coords[2]->AsNumber()
						));
					}
				}
			}
			OutEvent.Tracks.Add(MoveTemp(Track));
		}
	}

	// --- Calo Hits ---
	const TArray<TSharedPtr<FJsonValue>>* CaloArr;
	if (Root->TryGetArrayField(TEXT("calo_hits"), CaloArr))
	{
		for (const TSharedPtr<FJsonValue>& HitVal : *CaloArr)
		{
			const TSharedPtr<FJsonObject>& HitObj = HitVal->AsObject();
			if (!HitObj.IsValid()) continue;

			FEDMCaloHit Hit;
			Hit.EnergyGeV      = (float)HitObj->GetNumberField(TEXT("energy_gev"));
			Hit.CollectionName = HitObj->GetStringField(TEXT("collection"));

			const TArray<TSharedPtr<FJsonValue>>* PosArr;
			if (HitObj->TryGetArrayField(TEXT("position"), PosArr) && PosArr->Num() >= 3)
			{
				Hit.Position = FVector(
					(float)(*PosArr)[0]->AsNumber(),
					(float)(*PosArr)[1]->AsNumber(),
					(float)(*PosArr)[2]->AsNumber()
				);
			}
			OutEvent.CaloHits.Add(MoveTemp(Hit));
		}
	}

	// --- MC Particles ---
	const TArray<TSharedPtr<FJsonValue>>* MCArr;
	if (Root->TryGetArrayField(TEXT("mc_particles"), MCArr))
	{
		for (const TSharedPtr<FJsonValue>& MCVal : *MCArr)
		{
			const TSharedPtr<FJsonObject>& MCObj = MCVal->AsObject();
			if (!MCObj.IsValid()) continue;

			FEDMMCParticle MC;
			MC.PDG    = MCObj->GetIntegerField(TEXT("pdg"));
			MC.Charge = (float)MCObj->GetNumberField(TEXT("charge"));
			MC.Status = MCObj->GetIntegerField(TEXT("status"));

			auto ReadVec3 = [&](const FString& Key, FVector& OutVec)
			{
				const TArray<TSharedPtr<FJsonValue>>* Arr;
				if (MCObj->TryGetArrayField(Key, Arr) && Arr->Num() >= 3)
				{
					OutVec = FVector(
						(float)(*Arr)[0]->AsNumber(),
						(float)(*Arr)[1]->AsNumber(),
						(float)(*Arr)[2]->AsNumber()
					);
				}
			};

			ReadVec3(TEXT("vertex"),     MC.Vertex);
			ReadVec3(TEXT("end_vertex"), MC.EndVertex);
			ReadVec3(TEXT("momentum_gev"), MC.MomentumGeV);

			OutEvent.MCParticles.Add(MoveTemp(MC));
		}
	}

	return true;
}
