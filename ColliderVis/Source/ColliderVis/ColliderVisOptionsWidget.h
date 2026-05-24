// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "DetectorVisibilityConfig.h"
#include "ColliderVisOptionsWidget.generated.h"

class AEventDisplayManager;
class ADetectorVisibilityManager;
class AColliderVisHUD;

/**
 * C++ base class for WBP_Options — the unified in-game options menu.
 *
 * HOW TO USE (see UE5_SETUP.md § Options Menu):
 *   1. Create a Widget Blueprint in Content/UI/ named "WBP_Options".
 *   2. Reparent it to UColliderVisOptionsWidget (Class Settings → Parent Class).
 *   3. Build your UI layout using the BlueprintCallable functions below as
 *      button click events and the BlueprintImplementableEvents to update labels.
 *
 * SECTIONS:
 *   Events    — load file, previous/next event, event counter
 *   Detector  — scrollable list of sub-detector visibility toggles
 *   Close     — resume button / Esc key
 *
 * The menu opens/closes via AColliderVisHUD::ToggleMenu(), which is called
 * when the player presses Esc (desktop) or the menu button (VR controller).
 */
UCLASS(Abstract, BlueprintType, Blueprintable)
class COLLIDERVIS_API UColliderVisOptionsWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	// ── Current state (read in Blueprint to populate labels) ─────────────────

	/** Current event index shown in the counter label */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis|State")
	int32 CurrentEventIndex = 0;

	/** Total events available in the loaded file */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis|State")
	int32 TotalEvents = 0;

	/** Path of the currently loaded file */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis|State")
	FString CurrentFilePath;

	/** True while a file is being converted/loaded — use to show a spinner */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis|State")
	bool bLoading = false;

	// ── Event controls ────────────────────────────────────────────────────────

	/**
	 * Opens the native OS file picker (Mac/Windows/Linux).
	 * On Android/Quest the file picker is unavailable — OnFilePickerNotAvailable
	 * fires so Blueprint can reveal an on-screen path text box instead.
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Events")
	void BrowseAndLoadFile();

	/** Load a specific file path directly (for Quest or typed-in paths). */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Events")
	void RequestLoadFile(const FString& FilePath);

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Events")
	void RequestNextEvent();

	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Events")
	void RequestPreviousEvent();

	/** Jump to a specific event (0-based index). Useful for a spinner/slider. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Events")
	void RequestLoadEventByIndex(int32 Index);

	// ── Detector visibility controls ──────────────────────────────────────────

	/**
	 * Returns the list of sub-detectors from the config data asset.
	 * Call this in OnMenuShown to build the toggle row list.
	 * Example Blueprint: For Each Loop over the array → Create WBP_DetectorRow
	 * for each entry → Add to VerticalBox.
	 */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	TArray<FSubDetectorEntry> GetSubDetectorList() const;

	/** Show or hide one sub-detector by name. Wire to a checkbox in WBP_DetectorRow. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	void SetSubDetectorVisible(FName SubDetectorName, bool bVisible);

	/** Query current visibility state — use to set checkbox state when building the list. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	bool GetSubDetectorVisible(FName SubDetectorName) const;

	/** Show all or hide all sub-detectors at once. Wire to Show All / Hide All buttons. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	void SetAllSubDetectorsVisible(bool bVisible);

	// ── Close ─────────────────────────────────────────────────────────────────

	/** Hides the menu and resumes gameplay. Wire to the "Resume" / "Close" button. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu")
	void RequestClose();

	// ── Blueprint Implementable Events ────────────────────────────────────────
	// Override these in WBP_Options to update your widget layout.

	/** Fires when event index, total, or file changes — update counter & file label. */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnEventStateChanged(int32 NewIndex, int32 Total, const FString& FilePath);

	/** Fires after each SetSubDetectorVisible call — update the matching toggle row. */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnSubDetectorVisibilityChanged(FName SubDetectorName, bool bNowVisible);

	/**
	 * Fires when the menu first becomes visible.
	 * Use this to: (re)populate the detector toggle list, refresh labels.
	 * Example: For Each GetSubDetectorList() → create WBP_DetectorRow → add to VBox.
	 */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnMenuShown();

	/** Fires when the menu is hidden — stop any animations, etc. */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnMenuHidden();

	/**
	 * Fires just before the file conversion/load starts.
	 * Show a "Loading…" overlay or progress label.
	 */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnLoadingStarted(const FString& FilePath);

	/**
	 * Fires after load completes (or fails).
	 * Hide the loading overlay. If bSuccess is false, show an error label.
	 */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnLoadingFinished(bool bSuccess, int32 EventsLoaded);

	/**
	 * Fires on Android/Quest where no native file picker is available.
	 * Reveal an on-screen text box so the user can type the path manually.
	 */
	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnFilePickerNotAvailable();

protected:
	virtual void NativeConstruct() override;

private:
	UPROPERTY()
	AEventDisplayManager* EventDisplayManager = nullptr;

	UPROPERTY()
	ADetectorVisibilityManager* VisibilityManager = nullptr;

	/** Subscribed to EventDisplayManager::OnEventLoaded */
	UFUNCTION()
	void HandleEventLoaded(int32 EventIndex);

	/** Refresh CurrentEventIndex / TotalEvents / CurrentFilePath then fire OnEventStateChanged */
	void SyncEventState();
};
