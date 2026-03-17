// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisHUD.h"
#include "Blueprint/UserWidget.h"

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
	}
}
