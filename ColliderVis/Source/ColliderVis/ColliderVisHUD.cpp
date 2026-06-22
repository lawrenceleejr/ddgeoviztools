// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisHUD.h"
#include "Blueprint/UserWidget.h"
#include "Engine/Canvas.h"
#include "Engine/Texture2D.h"
#include "CanvasItem.h"
#include "Engine/LocalPlayer.h"
#include "Engine/GameViewportClient.h"

void AColliderVisHUD::BeginPlay()
{
	Super::BeginPlay();

	// Try to auto-load the widget class from the standard Content path.
	// "_C" suffix is required when loading Blueprint classes by path.
	if (!OptionsWidgetClass)
	{
		OptionsWidgetClass = LoadClass<UColliderVisOptionsWidget>(
			nullptr, TEXT("/Game/UI/WBP_Options.WBP_Options_C"));
	}

	// Pre-create the widget at startup so OnMenuShown has no first-frame delay.
	// It stays Collapsed until ShowMenu() is called.
	EnsureWidgetCreated();
}

void AColliderVisHUD::DrawHUD()
{
	Super::DrawHUD();

	if (!Canvas) return;

	// Lazy-load the logo once (the crisp 3600px USMCC mark; transparent background).
	if (!CornerLogo)
	{
		CornerLogo = LoadObject<UTexture2D>(nullptr, TEXT("/Game/UI/Textures/T_USMCCLogo.T_USMCCLogo"));
	}
	if (!CornerLogo || !CornerLogo->GetResource()) return;

	// Top-right corner watermark, always on. Translucent blend preserves the logo's
	// transparency so only the mark draws (no black box).
	const float Pad  = 28.f;
	const float Size = CornerLogoSize;
	const float X    = Canvas->SizeX - Size - Pad;
	const float Y    = Pad;

	FCanvasTileItem Tile(FVector2D(X, Y), CornerLogo->GetResource(), FVector2D(Size, Size), FLinearColor(1.f, 1.f, 1.f, 0.9f));
	Tile.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Tile);
}

void AColliderVisHUD::EnsureWidgetCreated()
{
	if (OptionsWidget) return;
	if (!OptionsWidgetClass) return;

	APlayerController* PC = GetOwningPlayerController();
	if (!PC) return;

	OptionsWidget = CreateWidget<UColliderVisOptionsWidget>(PC, OptionsWidgetClass);
	if (OptionsWidget)
	{
		// Z-order 100: always renders on top of any other widgets
		OptionsWidget->AddToViewport(100);
		OptionsWidget->SetVisibility(ESlateVisibility::Collapsed);
	}
}

void AColliderVisHUD::ShowMenu()
{
	if (bMenuOpen) return;

	EnsureWidgetCreated();
	if (!OptionsWidget) return;

	bMenuOpen = true;
	OptionsWidget->SetVisibility(ESlateVisibility::Visible);
	// Re-sync the checkbox states from live state each open (the widget is created
	// once and cached, so they'd otherwise go stale vs the in-world keys).
	OptionsWidget->RefreshOpenState();
	OptionsWidget->OnMenuShown();
	ApplyInputMode(true);
}

void AColliderVisHUD::HideMenu()
{
	if (!bMenuOpen) return;
	if (!OptionsWidget) return;

	bMenuOpen = false;
	OptionsWidget->SetVisibility(ESlateVisibility::Collapsed);
	OptionsWidget->OnMenuHidden();
	ApplyInputMode(false);
}

void AColliderVisHUD::ToggleMenu()
{
	if (bMenuOpen)
		HideMenu();
	else
		ShowMenu();
}

void AColliderVisHUD::ApplyInputMode(bool bInMenuOpen)
{
	APlayerController* PC = GetOwningPlayerController();
	if (!PC) return;

	if (bInMenuOpen)
	{
		// Show the cursor and allow it to interact with the widget.
		// GameAndUI keeps game inputs (Esc / controller menu button) active
		// so the player can close the menu with the same key that opened it,
		// and VR controller thumbstick can drive the on-screen cursor.
		FInputModeGameAndUI InputMode;
		if (OptionsWidget)
		{
			InputMode.SetWidgetToFocus(OptionsWidget->TakeWidget());
		}
		InputMode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		PC->SetInputMode(InputMode);
		PC->bShowMouseCursor = true;
	}
	else
	{
		PC->SetInputMode(FInputModeGameOnly());
		PC->bShowMouseCursor = false;
		// Forcibly (re)capture + lock the mouse to the viewport. Toggling fullscreen or
		// closing the menu can drop the capture on the recreated viewport, which zeroes
		// the mouse delta and breaks mouse-look in fullscreen. Re-asserting the capture
		// modes here (in addition to the DefaultInput.ini defaults) makes look reliable.
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
}
