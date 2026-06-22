// Copyright ColliderVis Project. All Rights Reserved.
#include "SplashWidget.h"
#include "Engine/Texture2D.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundBase.h"
#include "Engine/LocalPlayer.h"
#include "Engine/GameViewportClient.h"
#include "TimerManager.h"
#include "Engine/World.h"
#include "Blueprint/WidgetTree.h"
#include "Components/Border.h"
#include "Components/Overlay.h"
#include "Components/OverlaySlot.h"
#include "Components/SizeBox.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Components/Image.h"
#include "Components/TextBlock.h"
#include "Styling/CoreStyle.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "TextureResource.h"

TSharedRef<SWidget> USplashWidget::RebuildWidget()
{
	// Build the entire splash tree in C++ (no designer dependency). Composition:
	//   [Overlay]
	//     ├─ pure-black base fill (guarantees true black at the very edges)
	//     ├─ full-screen radial-gradient backdrop (soft glow center → black edges)
	//     └─ centered content column: logo hero · hairline · tagline, with the
	//        credit line anchored low and small. Generous negative space throughout.
	if (WidgetTree)
	{
		UOverlay* Root = WidgetTree->ConstructWidget<UOverlay>(UOverlay::StaticClass(), TEXT("SplashRoot"));
		WidgetTree->RootWidget = Root;

		// ── Layer 0: true-black base ──────────────────────────────────────────
		UBorder* Base = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass(), TEXT("SplashBase"));
		Base->SetBrushColor(FLinearColor(0.f, 0.f, 0.f, 1.f));
		if (UOverlaySlot* BaseSlot = Root->AddChildToOverlay(Base))
		{
			BaseSlot->SetHorizontalAlignment(HAlign_Fill);
			BaseSlot->SetVerticalAlignment(VAlign_Fill);
		}

		// ── Layer 1: radial-gradient backdrop (asset-free, transient texture) ─
		UImage* Backdrop = WidgetTree->ConstructWidget<UImage>(UImage::StaticClass(), TEXT("SplashBackdrop"));
		if (UTexture2D* GradTex = BuildBackdropGradient())
		{
			// Stretch the small gradient across the whole screen for a smooth wash.
			Backdrop->SetBrushFromTexture(GradTex, /*bMatchSize*/ false);
			Backdrop->Brush.SetImageSize(FVector2D(1.f, 1.f));
			Backdrop->Brush.DrawAs = ESlateBrushDrawType::Image;
			Backdrop->Brush.Tiling = ESlateBrushTileType::NoTile;
		}
		if (UOverlaySlot* BackSlot = Root->AddChildToOverlay(Backdrop))
		{
			BackSlot->SetHorizontalAlignment(HAlign_Fill);
			BackSlot->SetVerticalAlignment(VAlign_Fill);
		}

		// ── Layer 2: content layer (faded in over the opaque black base) ─────
		// Everything below lives under ContentRoot so the fade-IN raises only the
		// logo/tagline/credit out of pure black, leaving the black base solid.
		UOverlay* Content = WidgetTree->ConstructWidget<UOverlay>(UOverlay::StaticClass(), TEXT("SplashContent"));
		ContentRoot = Content;
		if (UOverlaySlot* ContentSlot = Root->AddChildToOverlay(Content))
		{
			ContentSlot->SetHorizontalAlignment(HAlign_Fill);
			ContentSlot->SetVerticalAlignment(VAlign_Fill);
		}

		// Centered content column.
		UVerticalBox* VB = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass(), TEXT("SplashVBox"));
		if (UOverlaySlot* VBSlot = Content->AddChildToOverlay(VB))
		{
			VBSlot->SetHorizontalAlignment(HAlign_Center);
			VBSlot->SetVerticalAlignment(VAlign_Center);
		}

		// Logo hero, wrapped in a SizeBox so its height can track the viewport.
		LogoSizeBox = WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass(), TEXT("SplashLogoSizer"));
		UImage* Logo = WidgetTree->ConstructWidget<UImage>(UImage::StaticClass(), TEXT("SplashLogo"));
		if (UTexture2D* Tex = GetLogoTexture())
		{
			Logo->SetBrushFromTexture(Tex, /*bMatchSize*/ false);
			const float W = static_cast<float>(Tex->GetSizeX());
			const float H = static_cast<float>(Tex->GetSizeY());
			LogoSourceSize = FVector2D(W > 0.f ? W : 1.f, H > 0.f ? H : 1.f);
		}
		LogoSizeBox->AddChild(Logo);
		// Sensible default before NativeConstruct measures the real viewport.
		ResizeLogoToViewport();
		if (UVerticalBoxSlot* LSlot = VB->AddChildToVerticalBox(LogoSizeBox))
		{
			LSlot->SetHorizontalAlignment(HAlign_Center);
			LSlot->SetPadding(FMargin(0.f, 0.f, 0.f, 36.f));
		}

		// Hairline rule — a quiet divider that anchors the typographic block.
		UBorder* Rule = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass(), TEXT("SplashRule"));
		Rule->SetBrushColor(FLinearColor(0.78f, 0.82f, 0.88f, 0.28f));
		USizeBox* RuleSizer = WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass(), TEXT("SplashRuleSizer"));
		RuleSizer->SetWidthOverride(132.f);
		RuleSizer->SetHeightOverride(1.f);
		RuleSizer->AddChild(Rule);
		if (UVerticalBoxSlot* RSlot = VB->AddChildToVerticalBox(RuleSizer))
		{
			RSlot->SetHorizontalAlignment(HAlign_Center);
			RSlot->SetPadding(FMargin(0.f, 0.f, 0.f, 18.f));
		}

		// Tagline — secondary hierarchy: small-caps feel via UPPERCASE + tracking.
		UTextBlock* Tagline = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), TEXT("SplashTagline"));
		Tagline->SetText(TaglineText);
		Tagline->SetJustification(ETextJustify::Center);
		{
			FSlateFontInfo TagFont = FCoreStyle::GetDefaultFontStyle("Bold", 15);
			TagFont.LetterSpacing = 540; // generous tracking reads as refined small-caps
			Tagline->SetFont(TagFont);
		}
		Tagline->SetColorAndOpacity(FSlateColor(FLinearColor(0.80f, 0.85f, 0.92f, 0.92f)));
		if (UVerticalBoxSlot* TSlot = VB->AddChildToVerticalBox(Tagline))
		{
			TSlot->SetHorizontalAlignment(HAlign_Center);
		}

		// ── Credit line — tertiary, anchored low and unobtrusive ─────────────
		UTextBlock* Credit = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), TEXT("SplashCredit"));
		Credit->SetText(CreditText);
		Credit->SetJustification(ETextJustify::Center);
		{
			FSlateFontInfo CreditFont = FCoreStyle::GetDefaultFontStyle("Regular", 12);
			CreditFont.LetterSpacing = 120;
			Credit->SetFont(CreditFont);
		}
		Credit->SetColorAndOpacity(FSlateColor(FLinearColor(0.62f, 0.66f, 0.72f, 0.62f)));
		if (UOverlaySlot* CSlot = Content->AddChildToOverlay(Credit))
		{
			CSlot->SetHorizontalAlignment(HAlign_Center);
			CSlot->SetVerticalAlignment(VAlign_Bottom);
			CSlot->SetPadding(FMargin(0.f, 0.f, 0.f, 48.f));
		}
	}

	return Super::RebuildWidget();
}

UTexture2D* USplashWidget::BuildBackdropGradient() const
{
	// A radial wash: a faint cool-tinted glow at center easing to pure black at the
	// edges (a soft vignette). 256² is plenty since the brush is stretched & filtered.
	constexpr int32 Size = 256;
	UTexture2D* Tex = UTexture2D::CreateTransient(Size, Size, PF_B8G8R8A8);
	if (!Tex)
	{
		return nullptr;
	}
	Tex->SRGB = true;
	Tex->Filter = TF_Bilinear;
	Tex->AddressX = TA_Clamp;
	Tex->AddressY = TA_Clamp;

	FTexturePlatformData* PlatformData = Tex->GetPlatformData();
	if (!PlatformData || PlatformData->Mips.Num() == 0)
	{
		return nullptr;
	}
	FTexture2DMipMap& Mip = PlatformData->Mips[0];
	uint8* Data = static_cast<uint8*>(Mip.BulkData.Lock(LOCK_READ_WRITE));
	if (!Data)
	{
		Mip.BulkData.Unlock();
		return nullptr;
	}

	// Center colour: a near-black with a faint blue lift (matches the UMG accent
	// family). Edge colour: pure black. Smoothstep keeps the falloff buttery.
	const FLinearColor CenterCol(0.043f, 0.055f, 0.078f); // ~#0B0E14
	const FLinearColor EdgeCol(0.f, 0.f, 0.f);
	const float Cx = (Size - 1) * 0.5f;
	const float Cy = (Size - 1) * 0.5f;
	const float MaxR = FMath::Sqrt(Cx * Cx + Cy * Cy);

	for (int32 Y = 0; Y < Size; ++Y)
	{
		for (int32 X = 0; X < Size; ++X)
		{
			const float Dx = (X - Cx);
			const float Dy = (Y - Cy);
			float T = FMath::Sqrt(Dx * Dx + Dy * Dy) / MaxR; // 0 center → 1 corner
			T = FMath::Clamp(T, 0.f, 1.f);
			// Smoothstep, biased so the lit core stays compact and the field is mostly black.
			const float S = T * T * (3.f - 2.f * T);
			const FLinearColor C = FMath::Lerp(CenterCol, EdgeCol, S);
			uint8* P = Data + (static_cast<int64>(Y) * Size + X) * 4;
			// PF_B8G8R8A8 byte order: B, G, R, A.
			P[0] = static_cast<uint8>(FMath::Clamp(C.B, 0.f, 1.f) * 255.f + 0.5f);
			P[1] = static_cast<uint8>(FMath::Clamp(C.G, 0.f, 1.f) * 255.f + 0.5f);
			P[2] = static_cast<uint8>(FMath::Clamp(C.R, 0.f, 1.f) * 255.f + 0.5f);
			P[3] = 255;
		}
	}

	Mip.BulkData.Unlock();
	Tex->UpdateResource();
	return Tex;
}

void USplashWidget::ResizeLogoToViewport()
{
	if (!LogoSizeBox)
	{
		return;
	}

	// Height as a fraction of the viewport; width derived to preserve aspect.
	float ViewportH = 1080.f; // reasonable fallback before the viewport is known
	if (GEngine && GEngine->GameViewport)
	{
		FVector2D VP;
		GEngine->GameViewport->GetViewportSize(VP);
		if (VP.Y > 1.f)
		{
			ViewportH = static_cast<float>(VP.Y);
		}
	}

	const float Frac = FMath::Clamp(LogoHeightFraction, 0.1f, 0.9f);
	const float TargetH = ViewportH * Frac;
	const float Aspect = (LogoSourceSize.Y > 0.f) ? (LogoSourceSize.X / LogoSourceSize.Y) : 1.f;
	const float TargetW = TargetH * Aspect;

	LogoSizeBox->SetHeightOverride(TargetH);
	LogoSizeBox->SetWidthOverride(TargetW);
}

USplashWidget::USplashWidget(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	// Default soft reference to the imported USMCC logo. WBP_Splash may override.
	// Orchestrator: import Tools/_assets/USMCCLogo_circles_3600.png (3600²,
	// transparent) to /Game/UI/Textures/T_USMCCLogo to feed the hi-res hero.
	LogoTexture = TSoftObjectPtr<UTexture2D>(
		FSoftObjectPath(TEXT("/Game/UI/Textures/T_USMCCLogo.T_USMCCLogo")));

	TaglineText = FText::FromString(TEXT("INTERACTIVE EVENT DISPLAY"));

	CreditText = FText::FromString(TEXT("Lawrence Lee · University of Tennessee · muoncollider.us"));

	// Default soft reference to the imported CC0 whoosh. WBP_Splash may override.
	SplashWhooshSound = TSoftObjectPtr<USoundBase>(
		FSoftObjectPath(TEXT("/Game/Audio/S_SplashWhoosh.S_SplashWhoosh")));
}

void USplashWidget::NativeConstruct()
{
	Super::NativeConstruct();

	// Make sure key/click events reach this widget so any-key dismiss works.
	SetIsFocusable(true);
	SetKeyboardFocus();

	// Now that the viewport exists, size the logo hero to LogoHeightFraction of it.
	ResizeLogoToViewport();

	// The whole widget is opaque from frame one, so the black base covers the
	// scene immediately — the screen reads as PURE BLACK at launch. The fade-IN
	// then raises only ContentRoot (logo / tagline / credit) out of that black.
	SetRenderOpacity(1.0f);
	if (FadeInSeconds > 0.0f && ContentRoot)
	{
		ContentRoot->SetRenderOpacity(0.0f);
		FadeState = EFadeState::FadingIn;
		FadeElapsed = 0.0f;
	}
	else
	{
		if (ContentRoot)
		{
			ContentRoot->SetRenderOpacity(1.0f);
		}
		FadeState = EFadeState::None;
	}

	// Let the Blueprint populate the logo brush / credit and start any animation.
	OnSplashShown();

	// Cue the whoosh as the splash appears (guarded; null-safe).
	PlayWhoosh();

	// Auto-dismiss after DisplaySeconds (skip if 0 — wait for input only).
	if (DisplaySeconds > 0.0f)
	{
		if (UWorld* World = GetWorld())
		{
			World->GetTimerManager().SetTimer(
				AutoDismissTimer, this, &USplashWidget::Dismiss, DisplaySeconds, false);
		}
	}
}

void USplashWidget::NativeTick(const FGeometry& MyGeometry, float InDeltaTime)
{
	Super::NativeTick(MyGeometry, InDeltaTime);

	if (FadeState == EFadeState::None)
	{
		return;
	}

	FadeElapsed += InDeltaTime;

	if (FadeState == EFadeState::FadingIn)
	{
		// Raise ONLY the content out of the opaque black base (fade up from black).
		const float Alpha = (FadeInSeconds > 0.0f) ? FMath::Clamp(FadeElapsed / FadeInSeconds, 0.0f, 1.0f) : 1.0f;
		if (ContentRoot)
		{
			ContentRoot->SetRenderOpacity(Alpha);
		}
		if (Alpha >= 1.0f)
		{
			FadeState = EFadeState::None;
		}
	}
	else // FadingOut
	{
		// Drop the WHOLE widget (black base included) to reveal the detector scene
		// already loaded behind the splash — a smooth dissolve into 3D, no reload.
		const float Alpha = (FadeOutSeconds > 0.0f) ? FMath::Clamp(FadeElapsed / FadeOutSeconds, 0.0f, 1.0f) : 1.0f;
		SetRenderOpacity(1.0f - Alpha);
		if (Alpha >= 1.0f)
		{
			FadeState = EFadeState::None;
			// Fade-out complete — tear down and reveal the scene.
			FinishDismiss();
		}
	}
}

void USplashWidget::PlayWhoosh()
{
	if (bWhooshPlayed || SplashWhooshSound.IsNull())
	{
		return;
	}
	bWhooshPlayed = true;

	// Synchronous load is fine for a splash shown before the game level.
	// Mellow + subtle: low volume so the intro swell is a soft cue, not a harsh whoosh.
	if (USoundBase* Sound = SplashWhooshSound.LoadSynchronous())
	{
		UGameplayStatics::PlaySound2D(this, Sound, /*VolumeMultiplier=*/0.45f);
	}
}

UTexture2D* USplashWidget::GetLogoTexture()
{
	if (LogoTexture.IsNull())
	{
		return nullptr;
	}
	// Synchronous load is fine for a splash screen shown before the game level.
	return LogoTexture.LoadSynchronous();
}

void USplashWidget::Dismiss()
{
	// Guarded so it runs once: the first call starts the cinematic fade-out;
	// further calls (e.g. extra key presses during the fade) are ignored.
	if (bDismissed)
	{
		return;
	}
	bDismissed = true;

	// Stop the auto-dismiss timer now — input or timeout has triggered dismissal.
	if (UWorld* World = GetWorld())
	{
		World->GetTimerManager().ClearTimer(AutoDismissTimer);
	}

	if (FadeOutSeconds > 0.0f)
	{
		// Kick off the fade-out; NativeTick lerps opacity 1 → 0 then calls FinishDismiss().
		FadeState = EFadeState::FadingOut;
		FadeElapsed = 0.0f;
	}
	else
	{
		// No fade requested — hand off immediately.
		FinishDismiss();
	}
}

void USplashWidget::FinishDismiss()
{
	RemoveFromParent();

	// Restore normal game input before handing off to the detector level.
	if (APlayerController* PC = GetOwningPlayer())
	{
		PC->SetInputMode(FInputModeGameOnly());
		PC->bShowMouseCursor = false;
		// Force the viewport to capture + lock the mouse so mouse-look works in
		// fullscreen right from the first frame of gameplay.
		if (ULocalPlayer* LP = PC->GetLocalPlayer())
		{
			if (UGameViewportClient* VPC = LP->ViewportClient)
			{
				VPC->SetMouseCaptureMode(EMouseCaptureMode::CapturePermanently);
				VPC->SetMouseLockMode(EMouseLockMode::LockAlways);
				VPC->SetHideCursorDuringCapture(true);
			}
		}
	}

	// The splash is shown OVER the detector level (it's the GameDefaultMap), so in
	// the normal flow we simply removed ourselves above — the fade-out has already
	// dissolved into the live 3D scene; no reload needed. Only open the level
	// explicitly if we somehow ended up splashing over a *different* map.
	bool bAlreadyInMainLevel = false;
	if (UWorld* World = GetWorld())
	{
		bAlreadyInMainLevel = World->GetMapName().Contains(MainLevelName.ToString());
	}
	if (!bAlreadyInMainLevel)
	{
		UGameplayStatics::OpenLevel(this, MainLevelName);
	}
}

FReply USplashWidget::NativeOnKeyDown(const FGeometry& InGeometry, const FKeyEvent& InKeyEvent)
{
	Dismiss();
	return FReply::Handled();
}

FReply USplashWidget::NativeOnMouseButtonDown(const FGeometry& InGeometry, const FPointerEvent& InMouseEvent)
{
	Dismiss();
	return FReply::Handled();
}
