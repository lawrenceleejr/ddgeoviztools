// Copyright ColliderVis Project. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "ColliderVisOptionsWidget.h"
#include "ColliderVisHUD.generated.h"

/**
 * HUD for ColliderVis.  Owns the options menu widget and handles show/hide.
 *
 * Activated automatically: AColliderVisGameMode sets HUDClass = this class
 * in its constructor, so every explore and VR session gets a HUD.
 *
 * The widget itself is a Blueprint child of UColliderVisOptionsWidget.
 * The C++ tries to auto-discover it at /Game/UI/WBP_Options when it is not
 * explicitly assigned (see OptionsWidgetClass below).
 *
 * OPEN / CLOSE:
 *   - Esc (or V) on desktop → AColliderVisCharacter calls ToggleMenu()
 *   - Menu button on Quest controller → AColliderVisVRPawn calls ToggleMenu()
 *   - "Resume" button inside the widget → UColliderVisOptionsWidget::RequestClose()
 *   All three paths converge here.
 *
 * INPUT MODE while menu is open:
 *   GameAndUI — the mouse cursor appears and routes clicks to the widget;
 *   game controller / keyboard input is also still processed so Esc can
 *   close the menu and VR controller thumbstick can drive the cursor.
 *   The game is NOT paused (VR needs continuous rendering; the event
 *   visualization can stay live while options are open).
 */
UCLASS(Blueprintable)
class COLLIDERVIS_API AColliderVisHUD : public AHUD
{
	GENERATED_BODY()

public:
	/**
	 * Widget class to instantiate.  Set this to WBP_Options in a Blueprint
	 * child of this HUD class, or place WBP_Options at /Game/UI/WBP_Options
	 * and the C++ auto-discovers it at BeginPlay.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ColliderVis")
	TSubclassOf<UColliderVisOptionsWidget> OptionsWidgetClass;

	/** The live widget instance — null before the menu is first opened. */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis")
	UColliderVisOptionsWidget* OptionsWidget = nullptr;

	/** True while the menu is currently visible. */
	UPROPERTY(BlueprintReadOnly, Category = "ColliderVis")
	bool bMenuOpen = false;

	/** Show the options menu. Does nothing if already open. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis")
	void ShowMenu();

	/** Hide the options menu. Does nothing if already closed. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis")
	void HideMenu();

	/** Show if closed, hide if open. */
	UFUNCTION(BlueprintCallable, Category = "ColliderVis")
	void ToggleMenu();

protected:
	virtual void BeginPlay() override;

	/** Draws the persistent USMCC logo in the top-right corner every frame. */
	virtual void DrawHUD() override;

private:
	/** Create the widget once and add it to the viewport (collapsed). */
	void EnsureWidgetCreated();

	/** Cached USMCC logo for the always-on corner watermark (loaded lazily in DrawHUD). */
	UPROPERTY(Transient)
	UTexture2D* CornerLogo = nullptr;

	/** Corner logo size in pixels (square). */
	UPROPERTY(EditAnywhere, Category = "ColliderVis")
	float CornerLogoSize = 110.f;

	/** Switch player controller input mode to match bInMenuOpen. */
	void ApplyInputMode(bool bInMenuOpen);
};
