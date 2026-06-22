// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisGameInstance.h"
#include "SplashWidget.h"
#include "Blueprint/UserWidget.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "UObject/UObjectGlobals.h"

void UColliderVisGameInstance::Init()
{
	Super::Init();

	// We can't create a widget in Init() — there is no world/player controller
	// yet. Wait until the first map finishes loading, then show the splash.
	FCoreUObjectDelegates::PostLoadMapWithWorld.AddUObject(
		this, &UColliderVisGameInstance::HandlePostLoadMap);
}

void UColliderVisGameInstance::HandlePostLoadMap(UWorld* LoadedWorld)
{
	if (bSplashShown)
	{
		return;
	}

	// If a specific splash map is configured, only show the splash there.
	if (!SplashMapName.IsNone() && LoadedWorld)
	{
		const FName CurrentMap(*LoadedWorld->GetMapName());
		// World map names may carry a streaming prefix (e.g. "UEDPIE_0_"),
		// so match on a contains-test rather than strict equality.
		if (!CurrentMap.ToString().Contains(SplashMapName.ToString()))
		{
			return;
		}
	}

	ShowSplash();
}

void UColliderVisGameInstance::ShowSplash()
{
	if (bSplashShown)
	{
		return;
	}

	TSubclassOf<USplashWidget> WidgetClass = ResolveSplashWidgetClass();
	if (!WidgetClass)
	{
		// No splash asset available — proceed without it rather than blocking boot.
		return;
	}

	APlayerController* PC = GetFirstLocalPlayerController();
	if (!PC)
	{
		// No controller yet — try again on the next map load.
		return;
	}

	USplashWidget* Splash = CreateWidget<USplashWidget>(PC, WidgetClass);
	if (!Splash)
	{
		return;
	}

	bSplashShown = true;

	// Z-order high so it covers the level and HUD.
	Splash->AddToViewport(1000);

	// Route input to the splash so any-key / click dismiss works immediately.
	FInputModeUIOnly InputMode;
	InputMode.SetWidgetToFocus(Splash->TakeWidget());
	PC->SetInputMode(InputMode);
	PC->bShowMouseCursor = true;
}

TSubclassOf<USplashWidget> UColliderVisGameInstance::ResolveSplashWidgetClass()
{
	if (SplashWidgetClass)
	{
		return SplashWidgetClass;
	}

	// Auto-discover from the standard Content path. "_C" suffix loads the
	// generated Blueprint class.
	TSubclassOf<USplashWidget> Loaded = LoadClass<USplashWidget>(
		nullptr, TEXT("/Game/UI/WBP_Splash.WBP_Splash_C"));

	return Loaded;
}
