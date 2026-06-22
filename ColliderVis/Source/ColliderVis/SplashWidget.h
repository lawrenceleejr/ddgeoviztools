// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "SplashWidget.generated.h"

class UTexture2D;
class USoundBase;
class USizeBox;

/**
 * C++ base class for WBP_Splash — the launch / title splash screen.
 *
 * HOW TO USE (orchestrator):
 *   1. Create a Widget Blueprint in Content/UI/ named "WBP_Splash".
 *   2. Reparent it to USplashWidget (Class Settings → Parent Class).
 *   3. Build the layout: an Image bound to the USMCC logo and a credit
 *      TextBlock. Read GetLogoTexture() / CreditText to populate them, or
 *      override OnSplashShown() for any intro animation.
 *   4. The widget is created and shown automatically by
 *      UColliderVisGameInstance at launch (no manual placement needed).
 *
 * FLOW:
 *   Splash appears → auto-dismisses after DisplaySeconds, OR the player
 *   presses any key / clicks → Dismiss() opens the main detector level
 *   (/Game/Maps/ColliderVisMain).
 *
 * The logo defaults to a soft reference at /Game/UI/Textures/T_USMCCLogo,
 * but the WBP_Splash asset may override LogoTexture in the designer.
 */
UCLASS(Abstract, BlueprintType, Blueprintable)
class COLLIDERVIS_API USplashWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	USplashWidget(const FObjectInitializer& ObjectInitializer);

	// ── Designer-facing content ───────────────────────────────────────────────

	/**
	 * Logo texture shown on the splash. Soft reference so the asset need not be
	 * loaded until the splash is shown. Defaults to /Game/UI/Textures/T_USMCCLogo;
	 * WBP_Splash may override it in the designer.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash")
	TSoftObjectPtr<UTexture2D> LogoTexture;

	/** Refined tagline shown directly under the logo (small-caps, tracked, muted). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash")
	FText TaglineText;

	/** Credit / attribution line shown at the very bottom, smaller and unobtrusive. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash")
	FText CreditText;

	/**
	 * Logo hero height as a fraction of the viewport height (aspect preserved).
	 * ~0.5 reads as a confident hero without overwhelming the negative space.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash", meta = (ClampMin = "0.1", ClampMax = "0.9"))
	float LogoHeightFraction = 0.5f;

	/** Seconds the splash stays up before auto-dismissing (0 = stay until input). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash", meta = (ClampMin = "0.0"))
	float DisplaySeconds = 4.0f;

	/** Level to open when the splash is dismissed. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash")
	FName MainLevelName = TEXT("ColliderVisMain");

	// ── Cinematic fade ────────────────────────────────────────────────────────

	/** Seconds for the fade-IN (render opacity 0 → 1) when the splash appears. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash|Fade", meta = (ClampMin = "0.0"))
	float FadeInSeconds = 1.5f;

	/** Seconds for the fade-OUT (render opacity 1 → 0) before the level opens. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash|Fade", meta = (ClampMin = "0.0"))
	float FadeOutSeconds = 1.0f;

	// ── Audio ─────────────────────────────────────────────────────────────────

	/**
	 * "Whoosh" sound played once when the splash becomes visible. Soft reference
	 * so the asset need not be loaded until shown. Defaults to /Game/Audio/S_SplashWhoosh
	 * (a CC0 sound — see Content/Audio/CREDITS.md). Replace freely; null is safe (no sound).
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Splash|Audio")
	TSoftObjectPtr<USoundBase> SplashWhooshSound;

	// ── Blueprint helpers ─────────────────────────────────────────────────────

	/**
	 * Synchronously loads (if needed) and returns the logo texture so an Image
	 * widget can use it. Call this in OnSplashShown to set the brush.
	 */
	UFUNCTION(BlueprintCallable, Category = "Splash")
	UTexture2D* GetLogoTexture();

	/**
	 * Removes the splash from the viewport and opens the main detector level.
	 * Safe to call multiple times — only the first call has an effect.
	 * Wire to a "Skip" button, or let auto-dismiss / any-key call it.
	 */
	UFUNCTION(BlueprintCallable, Category = "Splash")
	void Dismiss();

	/**
	 * Fires when the splash first becomes visible. Override in WBP_Splash to
	 * set the logo brush / credit text and play any fade-in animation.
	 */
	UFUNCTION(BlueprintImplementableEvent, Category = "Splash")
	void OnSplashShown();

protected:
	/** Builds the splash UI (dark bg + centered logo + credit) entirely in C++ so
	 *  WBP_Splash needs no designer work — mirrors the C++-built options menu. */
	virtual TSharedRef<SWidget> RebuildWidget() override;

	virtual void NativeConstruct() override;

	// Per-frame lerp drives SetRenderOpacity() for the fade-in/out (no UMG anim needed).
	virtual void NativeTick(const FGeometry& MyGeometry, float InDeltaTime) override;

	// Any-key / any-click dismiss. The widget captures focus so these fire.
	virtual FReply NativeOnKeyDown(const FGeometry& InGeometry, const FKeyEvent& InKeyEvent) override;
	virtual FReply NativeOnMouseButtonDown(const FGeometry& InGeometry, const FPointerEvent& InMouseEvent) override;

private:
	/** Which way the per-frame opacity lerp is currently driving. */
	enum class EFadeState : uint8
	{
		None,
		FadingIn,
		FadingOut
	};

	/** Plays the splash whoosh once (guarded), loading the soft ref synchronously. */
	void PlayWhoosh();

	/**
	 * Builds a transient radial-gradient texture (near-black center → pure black
	 * edges with a faint cool tint) used as the splash backdrop. Asset-free, so
	 * the splash stays self-contained. Returns nullptr on failure (caller falls
	 * back to a flat fill). Created lazily and kept alive by SetBrushFromTexture.
	 */
	UTexture2D* BuildBackdropGradient() const;

	/** Sizes the logo to LogoHeightFraction of the actual viewport (aspect kept). */
	void ResizeLogoToViewport();

	/** Logo sizer, cached so the hero size can track the real viewport height. */
	UPROPERTY(Transient)
	TObjectPtr<USizeBox> LogoSizeBox = nullptr;

	/**
	 * Holds the logo / tagline / credit. It is faded in (opacity 0 → 1) over the
	 * always-opaque black base, so the intro reads as "fade up from pure black"
	 * rather than fading the live scene down to black. The fade-OUT instead drops
	 * the whole-widget opacity, revealing the detector scene already behind it.
	 */
	UPROPERTY(Transient)
	TObjectPtr<class UWidget> ContentRoot = nullptr;

	/** Source pixel size of the loaded logo, used to preserve aspect on resize. */
	FVector2D LogoSourceSize = FVector2D(1.f, 1.f);

	/** Tears down the widget and opens the main level. Called when the fade-out completes. */
	void FinishDismiss();

	/** Guard so Dismiss() / OpenLevel only runs once. */
	bool bDismissed = false;

	/** Guard so the whoosh only plays once. */
	bool bWhooshPlayed = false;

	EFadeState FadeState = EFadeState::None;

	/** Elapsed seconds within the current fade. */
	float FadeElapsed = 0.0f;

	FTimerHandle AutoDismissTimer;
};
