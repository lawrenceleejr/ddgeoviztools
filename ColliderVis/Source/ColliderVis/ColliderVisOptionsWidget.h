// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "DetectorVisibilityConfig.h"
#include "ColliderVisOptionsWidget.generated.h"

class AEventDisplayManager;
class ADetectorVisibilityManager;
class AColliderVisHUD;

class UWidget;
class UButton;
class UTextBlock;
class USlider;
class UCheckBox;
class UScrollBox;
class UBorder;
class UVerticalBox;
class UHorizontalBox;
class UPanelWidget;

/**
 * C++ base class for the unified in-game options / pause menu.
 *
 * The ENTIRE menu UI (layout + styling + bindings) is constructed
 * programmatically in C++ in RebuildWidget() — there is no UMG designer
 * graph to wire up. This avoids the orphan/broken-event problems that came
 * from generating the Blueprint graph via MCP.
 *
 * SECTIONS (top → bottom):
 *   Header    — title, accent rule, credit line + clickable muoncollider.us link
 *   Detector  — Show All / Hide All + scrollable per-sub-detector visibility toggles
 *   Settings  — mouse-sensitivity slider, quality preset buttons, feature toggles
 *   Footer    — prominent RESUME button (+ Prev/Next event)
 *
 * The menu opens/closes via AColliderVisHUD; RequestClose() resumes gameplay.
 */
UCLASS(Abstract, BlueprintType, Blueprintable)
class COLLIDERVIS_API UColliderVisOptionsWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	/** Re-sync all live-state controls (detector + cutaway checkboxes) from current
	 *  state. Called by the HUD each time the menu opens so they don't go stale. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu")
	void RefreshOpenState();

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

	/** Returns the list of sub-detectors from the config data asset. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	TArray<FSubDetectorEntry> GetSubDetectorList() const;

	/** Show or hide one sub-detector by name. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	void SetSubDetectorVisible(FName SubDetectorName, bool bVisible);

	/** Query current visibility state. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	bool GetSubDetectorVisible(FName SubDetectorName) const;

	/** Show all or hide all sub-detectors at once. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu|Detector")
	void SetAllSubDetectorsVisible(bool bVisible);

	// ── Close ─────────────────────────────────────────────────────────────────

	/** Hides the menu and resumes gameplay. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis|Menu")
	void RequestClose();

	// ── Blueprint Implementable Events (kept for compatibility) ───────────────

	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnEventStateChanged(int32 NewIndex, int32 Total, const FString& FilePath);

	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnSubDetectorVisibilityChanged(FName SubDetectorName, bool bNowVisible);

	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnMenuShown();

	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnMenuHidden();

	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnLoadingStarted(const FString& FilePath);

	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnLoadingFinished(bool bSuccess, int32 EventsLoaded);

	UFUNCTION(BlueprintImplementableEvent, Category = "ColliderVis|Menu")
	void OnFilePickerNotAvailable();

protected:
	virtual void NativeConstruct() override;

	/** Builds the whole menu tree programmatically. */
	virtual TSharedRef<SWidget> RebuildWidget() override;

	// ── C++ click / value handlers (all UFUNCTION for AddDynamic) ─────────────

	UFUNCTION() void OnResumeClicked();
	UFUNCTION() void OnNextEventClicked();
	UFUNCTION() void OnPrevEventClicked();
	UFUNCTION() void OnShowAllClicked();
	UFUNCTION() void OnHideAllClicked();
	UFUNCTION() void OnCreditLinkClicked();

	UFUNCTION() void OnSensitivityChanged(float Value);

	/**
	 * Shared dispatcher for every sub-detector toggle. UMG's OnCheckStateChanged
	 * delegate carries no widget identity, so this handler reconciles ALL toggle
	 * rows against their managed visibility state — whichever box the user just
	 * flipped gets pushed through SetSubDetectorVisible. Cheap (one pass).
	 */
	UFUNCTION() void OnDetectorToggleChangedDispatch(bool bChecked);

	/** Any cutaway-quadrant checkbox changed: re-sync MPC_Cutaway Q1..Q4 from the
	 *  four checkbox states (checked = quadrant cut away / hidden). One pass. */
	UFUNCTION() void OnCutawayToggleChangedDispatch(bool bChecked);

	UFUNCTION() void OnQuality0Clicked();
	UFUNCTION() void OnQuality1Clicked();
	UFUNCTION() void OnQuality2Clicked();
	UFUNCTION() void OnQuality3Clicked();
	UFUNCTION() void OnQuality4Clicked();

	// Resolution selector
	UFUNCTION() void OnRes0Clicked();
	UFUNCTION() void OnRes1Clicked();
	UFUNCTION() void OnRes2Clicked();
	UFUNCTION() void OnRes3Clicked();
	UFUNCTION() void OnFullscreenClicked();

	UFUNCTION() void OnLumenChanged(bool bChecked);
	UFUNCTION() void OnVolumetricFogChanged(bool bChecked);
	UFUNCTION() void OnMotionBlurChanged(bool bChecked);
	UFUNCTION() void OnBloomChanged(bool bChecked);
	UFUNCTION() void OnDepthOfFieldChanged(bool bChecked);
	UFUNCTION() void OnFilmGrainChanged(bool bChecked);
	UFUNCTION() void OnScreenSpaceShadowsChanged(bool bChecked);
	UFUNCTION() void OnNaniteChanged(bool bChecked);

private:
	UPROPERTY()
	AEventDisplayManager* EventDisplayManager = nullptr;

	UPROPERTY()
	ADetectorVisibilityManager* VisibilityManager = nullptr;

	UFUNCTION()
	void HandleEventLoaded(int32 EventIndex);

	void SyncEventState();

	// ── Construction helpers ───────────────────────────────────────────────────

	/** Discovers the level managers (idempotent — safe to call repeatedly). */
	void DiscoverManagers();

	/** Sets the quality preset and repaints the 5 quality buttons. */
	void ApplyQualityPreset(int32 Preset);
	void RefreshQualityButtons();
	void ApplyResolution(int32 W, int32 H);

	/** Re-reads visibility state into the checkbox rows (after Show/Hide All). */
	void RefreshDetectorCheckBoxes();

	/** Re-reads MPC_Cutaway Q1..Q4 into the cutaway checkboxes (call on menu open so
	 *  they don't go stale vs the number keys). */
	void RefreshCutawayCheckBoxes();

	/** A standard Roboto font of the given size. */
	FSlateFontInfo MakeFont(int32 Size, bool bBold = false) const;

	/** Creates a flat accent-on-hover styled text button bound to Handler. */
	UButton* MakeButton(const FString& Label, int32 FontSize,
	                    const FLinearColor& NormalFill, const FLinearColor& HoverFill,
	                    const FLinearColor& TextColor);

	/** A small uppercase tracked section header text block. */
	UTextBlock* MakeSectionHeader(const FString& Text);

	/** A body text label. */
	UTextBlock* MakeLabel(const FString& Text, int32 Size, const FLinearColor& Color);

	/** Builds one feature-toggle row (label + checkbox). */
	UHorizontalBox* MakeFeatureRow(const FString& Label, bool bInitialChecked,
	                              UCheckBox*& OutCheckBox);

	// ── Palette ─────────────────────────────────────────────────────────────────
	static const FLinearColor Accent;       // cyan
	static const FLinearColor PanelFill;     // dark translucent
	static const FLinearColor NearWhite;
	static const FLinearColor BodyGrey;
	static const FLinearColor MutedGrey;
	static const FLinearColor BtnNormal;
	static const FLinearColor BtnHover;

	// ── Widget references kept for runtime updates ──────────────────────────────

	UPROPERTY() USlider* SensitivitySlider = nullptr;
	UPROPERTY() UTextBlock* SensitivityValueText = nullptr;

	UPROPERTY() TArray<UButton*> QualityButtons;
	UPROPERTY() TArray<UButton*> ResolutionButtons;

	/** Parallel arrays: one checkbox per sub-detector, with its name. */
	UPROPERTY() TArray<UCheckBox*> DetectorCheckBoxes;
	TArray<FName> DetectorNames;

	/** One checkbox per phi cutaway quadrant (index 0..3 -> MPC_Cutaway Q1..Q4). */
	UPROPERTY() TArray<UCheckBox*> CutawayCheckBoxes;
};
