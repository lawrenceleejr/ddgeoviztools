#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "EventMenuWidget.generated.h"

class AEventDisplayManager;

/**
 * C++ base class for WBP_EventMenu.
 * Create WBP_EventMenu in the UE5 editor, reparent to UEventMenuWidget,
 * then implement the BlueprintImplementableEvents for UI layout.
 */
UCLASS(Abstract, BlueprintType, Blueprintable)
class COLLIDERVIS_API UEventMenuWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	/** Set by the owning HUD or character after construction */
	UPROPERTY(BlueprintReadWrite, Category = "ColliderVis")
	AEventDisplayManager* EventDisplayManager;

	/** Called from Blueprint "Load" button — triggers file conversion */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu")
	void RequestLoadFile(const FString& FilePath);

	/** Called from Blueprint "Next" button */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu")
	void RequestNextEvent();

	/** Override in Blueprint to update event counter label */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnEventIndexChanged(int32 NewIndex, int32 Total);

protected:
	virtual void NativeConstruct() override;

private:
	/** Subscribe to EventDisplayManager.OnEventLoaded */
	UFUNCTION()
	void HandleEventLoaded(int32 EventIndex);
};
