// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisOptionsWidget.h"
#include "ColliderVisHUD.h"
#include "EventDisplayManager.h"
#include "DetectorVisibilityManager.h"
#include "Kismet/GameplayStatics.h"

#if PLATFORM_DESKTOP
#include "DesktopPlatformModule.h"
#include "IDesktopPlatform.h"
#endif

void UColliderVisOptionsWidget::NativeConstruct()
{
	Super::NativeConstruct();

	// Auto-discover managers in the level
	TArray<AActor*> Found;

	UGameplayStatics::GetAllActorsOfClass(GetWorld(), AEventDisplayManager::StaticClass(), Found);
	if (Found.Num() > 0)
	{
		EventDisplayManager = Cast<AEventDisplayManager>(Found[0]);
	}

	Found.Empty();
	UGameplayStatics::GetAllActorsOfClass(GetWorld(), ADetectorVisibilityManager::StaticClass(), Found);
	if (Found.Num() > 0)
	{
		VisibilityManager = Cast<ADetectorVisibilityManager>(Found[0]);
	}

	// Subscribe to event-loaded delegate so the counter label stays current
	if (EventDisplayManager)
	{
		EventDisplayManager->OnEventLoaded.AddDynamic(this, &UColliderVisOptionsWidget::HandleEventLoaded);
		SyncEventState();
	}
}

// ── Event controls ────────────────────────────────────────────────────────────

void UColliderVisOptionsWidget::BrowseAndLoadFile()
{
#if PLATFORM_DESKTOP
	IDesktopPlatform* DesktopPlatform = FDesktopPlatformModule::Get();
	if (!DesktopPlatform)
	{
		OnFilePickerNotAvailable();
		return;
	}

	// Start in the directory of the currently loaded file if possible
	FString StartDir = FPaths::GetPath(CurrentFilePath);
	// Leave StartDir empty if no file is loaded yet — the OS picker will use the last-visited dir

	TArray<FString> Filenames;
	const bool bOpened = DesktopPlatform->OpenFileDialog(
		nullptr,
		TEXT("Load EDM4HEP Event File"),
		StartDir,
		TEXT(""),
		TEXT("EDM4HEP Files (*.root *.json)|*.root;*.json|All Files (*.*)|*.*"),
		EFileDialogFlags::None,
		Filenames
	);

	if (bOpened && Filenames.Num() > 0)
	{
		RequestLoadFile(Filenames[0]);
	}
#else
	// Android / Quest standalone — no native file picker.
	// Fire the BP event so the Blueprint can reveal an on-screen text-box.
	OnFilePickerNotAvailable();
#endif
}

void UColliderVisOptionsWidget::RequestLoadFile(const FString& FilePath)
{
	if (FilePath.IsEmpty() || !EventDisplayManager) return;

	bLoading = true;
	OnLoadingStarted(FilePath);

	const bool bOk = EventDisplayManager->LoadEDM4HEPFile(FilePath);

	bLoading = false;
	SyncEventState();
	OnLoadingFinished(bOk, TotalEvents);
}

void UColliderVisOptionsWidget::RequestNextEvent()
{
	if (EventDisplayManager)
	{
		EventDisplayManager->LoadNextEvent();
	}
}

void UColliderVisOptionsWidget::RequestPreviousEvent()
{
	if (!EventDisplayManager || TotalEvents == 0) return;

	// Wrap around when going past event 0
	const int32 Prev = (CurrentEventIndex - 1 + TotalEvents) % TotalEvents;
	EventDisplayManager->LoadEvent(Prev);
}

void UColliderVisOptionsWidget::RequestLoadEventByIndex(int32 Index)
{
	if (EventDisplayManager)
	{
		EventDisplayManager->LoadEvent(Index);
	}
}

// ── Detector visibility ───────────────────────────────────────────────────────

TArray<FSubDetectorEntry> UColliderVisOptionsWidget::GetSubDetectorList() const
{
	if (VisibilityManager && VisibilityManager->Config)
	{
		return VisibilityManager->Config->SubDetectors;
	}
	return {};
}

void UColliderVisOptionsWidget::SetSubDetectorVisible(FName SubDetectorName, bool bVisible)
{
	if (!VisibilityManager) return;
	VisibilityManager->SetSubDetectorVisible(SubDetectorName, bVisible);
	OnSubDetectorVisibilityChanged(SubDetectorName, bVisible);
}

bool UColliderVisOptionsWidget::GetSubDetectorVisible(FName SubDetectorName) const
{
	if (!VisibilityManager) return true;
	return VisibilityManager->IsSubDetectorVisible(SubDetectorName);
}

void UColliderVisOptionsWidget::SetAllSubDetectorsVisible(bool bVisible)
{
	if (!VisibilityManager || !VisibilityManager->Config) return;

	VisibilityManager->SetAllVisible(bVisible);

	// Fire per-detector event so every toggle row can update its state
	for (const FSubDetectorEntry& Entry : VisibilityManager->Config->SubDetectors)
	{
		OnSubDetectorVisibilityChanged(Entry.Name, bVisible);
	}
}

// ── Close ─────────────────────────────────────────────────────────────────────

void UColliderVisOptionsWidget::RequestClose()
{
	APlayerController* PC = GetOwningPlayer();
	if (!PC) return;

	if (AColliderVisHUD* HUD = Cast<AColliderVisHUD>(PC->GetHUD()))
	{
		HUD->HideMenu();
	}
}

// ── Private ───────────────────────────────────────────────────────────────────

void UColliderVisOptionsWidget::HandleEventLoaded(int32 /*EventIndex*/)
{
	SyncEventState();
}

void UColliderVisOptionsWidget::SyncEventState()
{
	if (EventDisplayManager)
	{
		CurrentEventIndex = EventDisplayManager->CurrentEventIndex;
		TotalEvents       = EventDisplayManager->TotalEvents;
		CurrentFilePath   = EventDisplayManager->CurrentFilePath;
	}
	OnEventStateChanged(CurrentEventIndex, TotalEvents, CurrentFilePath);
}
