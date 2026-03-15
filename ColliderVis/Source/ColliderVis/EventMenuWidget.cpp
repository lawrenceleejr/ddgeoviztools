#include "EventMenuWidget.h"
#include "EventDisplayManager.h"
#include "Kismet/GameplayStatics.h"

void UEventMenuWidget::NativeConstruct()
{
	Super::NativeConstruct();

	// Auto-find EventDisplayManager if not assigned
	if (!EventDisplayManager)
	{
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(GetWorld(), AEventDisplayManager::StaticClass(), Found);
		if (Found.Num() > 0)
		{
			EventDisplayManager = Cast<AEventDisplayManager>(Found[0]);
		}
	}

	// Subscribe to event-loaded delegate
	if (EventDisplayManager)
	{
		EventDisplayManager->OnEventLoaded.AddDynamic(this, &UEventMenuWidget::HandleEventLoaded);
	}
}

void UEventMenuWidget::RequestLoadFile(const FString& FilePath)
{
	if (EventDisplayManager)
	{
		EventDisplayManager->LoadEDM4HEPFile(FilePath);
	}
}

void UEventMenuWidget::RequestNextEvent()
{
	if (EventDisplayManager)
	{
		EventDisplayManager->LoadNextEvent();
	}
}

void UEventMenuWidget::HandleEventLoaded(int32 EventIndex)
{
	if (EventDisplayManager)
	{
		OnEventIndexChanged(EventIndex, EventDisplayManager->TotalEvents);
	}
}
