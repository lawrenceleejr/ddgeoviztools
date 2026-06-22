// Copyright ColliderVis Project. All Rights Reserved.
#include "ColliderVisOptionsWidget.h"
#include "ColliderVisHUD.h"
#include "ColliderVisCharacter.h"
#include "ColliderVisUserSettings.h"
#include "EventDisplayManager.h"
#include "DetectorVisibilityManager.h"

#include "Blueprint/WidgetTree.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/Overlay.h"
#include "Components/OverlaySlot.h"
#include "Components/Border.h"
#include "Components/BorderSlot.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Components/HorizontalBox.h"
#include "Components/HorizontalBoxSlot.h"
#include "Components/ScrollBox.h"
#include "Components/ScrollBoxSlot.h"
#include "Components/TextBlock.h"
#include "Components/Button.h"
#include "Components/ButtonSlot.h"
#include "Components/Slider.h"
#include "Components/CheckBox.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"
#include "Components/SizeBox.h"
#include "Components/SizeBoxSlot.h"
#include "Components/Spacer.h"

#include "Styling/CoreStyle.h"
#include "Kismet/GameplayStatics.h"
#include "Kismet/KismetSystemLibrary.h"

#if PLATFORM_DESKTOP
#include "DesktopPlatformModule.h"
#include "IDesktopPlatform.h"
#endif

// ── Palette ──────────────────────────────────────────────────────────────────
const FLinearColor UColliderVisOptionsWidget::Accent    = FLinearColor(0.18f, 0.77f, 1.0f, 1.0f);
const FLinearColor UColliderVisOptionsWidget::PanelFill  = FLinearColor(0.04f, 0.06f, 0.09f, 0.92f);
const FLinearColor UColliderVisOptionsWidget::NearWhite  = FLinearColor(0.94f, 0.96f, 0.98f, 1.0f);
const FLinearColor UColliderVisOptionsWidget::BodyGrey   = FLinearColor(0.78f, 0.81f, 0.85f, 1.0f);
const FLinearColor UColliderVisOptionsWidget::MutedGrey  = FLinearColor(0.50f, 0.54f, 0.60f, 1.0f);
const FLinearColor UColliderVisOptionsWidget::BtnNormal  = FLinearColor(0.09f, 0.12f, 0.16f, 1.0f);
const FLinearColor UColliderVisOptionsWidget::BtnHover   = FLinearColor(0.18f, 0.77f, 1.0f, 0.85f);

// ── Helpers ──────────────────────────────────────────────────────────────────

FSlateFontInfo UColliderVisOptionsWidget::MakeFont(int32 Size, bool bBold) const
{
	// Engine Roboto via the core style — always available, no asset load needed.
	FSlateFontInfo Font = FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Size);
	return Font;
}

UTextBlock* UColliderVisOptionsWidget::MakeLabel(const FString& Text, int32 Size, const FLinearColor& Color)
{
	UTextBlock* T = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass());
	T->SetText(FText::FromString(Text));
	T->SetFont(MakeFont(Size));
	T->SetColorAndOpacity(FSlateColor(Color));
	return T;
}

UTextBlock* UColliderVisOptionsWidget::MakeSectionHeader(const FString& Text)
{
	UTextBlock* T = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass());
	T->SetText(FText::FromString(Text.ToUpper()));
	FSlateFontInfo Font = MakeFont(14, true);
	Font.LetterSpacing = 300; // tracked
	T->SetFont(Font);
	T->SetColorAndOpacity(FSlateColor(Accent));
	return T;
}

UButton* UColliderVisOptionsWidget::MakeButton(const FString& Label, int32 FontSize,
	const FLinearColor& NormalFill, const FLinearColor& HoverFill, const FLinearColor& TextColor)
{
	UButton* Btn = WidgetTree->ConstructWidget<UButton>(UButton::StaticClass());

	FButtonStyle Style = Btn->GetStyle();

	FSlateBrush NormalBrush;
	NormalBrush.TintColor = FSlateColor(NormalFill);
	NormalBrush.DrawAs = ESlateBrushDrawType::RoundedBox;
	NormalBrush.OutlineSettings.CornerRadii = FVector4(6.f, 6.f, 6.f, 6.f);
	NormalBrush.OutlineSettings.RoundingType = ESlateBrushRoundingType::FixedRadius;

	FSlateBrush HoverBrush = NormalBrush;
	HoverBrush.TintColor = FSlateColor(HoverFill);

	FSlateBrush PressedBrush = NormalBrush;
	PressedBrush.TintColor = FSlateColor(HoverFill * 0.8f);

	Style.SetNormal(NormalBrush);
	Style.SetHovered(HoverBrush);
	Style.SetPressed(PressedBrush);
	Style.NormalPadding  = FMargin(16.f, 8.f);
	Style.PressedPadding = FMargin(16.f, 8.f);
	Btn->SetStyle(Style);

	UTextBlock* Txt = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass());
	Txt->SetText(FText::FromString(Label));
	Txt->SetFont(MakeFont(FontSize, true));
	Txt->SetColorAndOpacity(FSlateColor(TextColor));
	Txt->SetJustification(ETextJustify::Center);
	Btn->AddChild(Txt);

	return Btn;
}

UHorizontalBox* UColliderVisOptionsWidget::MakeFeatureRow(const FString& Label, bool bInitialChecked, UCheckBox*& OutCheckBox)
{
	UHorizontalBox* Row = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());

	UTextBlock* Lbl = MakeLabel(Label, 15, BodyGrey);
	if (UHorizontalBoxSlot* LSlot = Cast<UHorizontalBoxSlot>(Row->AddChild(Lbl)))
	{
		LSlot->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
		LSlot->SetVerticalAlignment(VAlign_Center);
		LSlot->SetPadding(FMargin(0.f, 4.f));
	}

	OutCheckBox = WidgetTree->ConstructWidget<UCheckBox>(UCheckBox::StaticClass());
	OutCheckBox->SetCheckedState(bInitialChecked ? ECheckBoxState::Checked : ECheckBoxState::Unchecked);
	if (UHorizontalBoxSlot* CSlot = Cast<UHorizontalBoxSlot>(Row->AddChild(OutCheckBox)))
	{
		CSlot->SetSize(FSlateChildSize(ESlateSizeRule::Automatic));
		CSlot->SetVerticalAlignment(VAlign_Center);
		CSlot->SetHorizontalAlignment(HAlign_Right);
	}

	return Row;
}

// ── Tree construction ────────────────────────────────────────────────────────

TSharedRef<SWidget> UColliderVisOptionsWidget::RebuildWidget()
{
	// Discard any designer-authored tree so there's no duplication, and rebuild
	// the whole thing in C++.
	if (WidgetTree)
	{
		WidgetTree->RootWidget = nullptr;
	}

	DiscoverManagers();

	// Root canvas so the dim backdrop can fill the whole screen.
	// Hit-testable so clicks land on the menu (the HUD enables GameAndUI + cursor).
	UCanvasPanel* Root = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass());
	WidgetTree->RootWidget = Root;
	Root->SetVisibility(ESlateVisibility::Visible);

	// 1) Full-screen dim backdrop — added FIRST so it sits behind the panel in
	//    z-order. Visible (not HitTestInvisible) so clicks outside the panel are
	//    swallowed rather than falling through to the game.
	UBorder* Backdrop = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
	Backdrop->SetBrushColor(FLinearColor(0.f, 0.f, 0.f, 0.6f));
	Backdrop->SetVisibility(ESlateVisibility::Visible);
	if (UCanvasPanelSlot* BackSlot = Cast<UCanvasPanelSlot>(Root->AddChild(Backdrop)))
	{
		BackSlot->SetAnchors(FAnchors(0.f, 0.f, 1.f, 1.f));
		BackSlot->SetOffsets(FMargin(0.f));
		BackSlot->SetZOrder(0);
	}

	// 2) Centered content panel.
	//    The panel is anchored to a CENTERED region of the viewport and its size
	//    is driven by a SizeBox that caps BOTH width and height. The height cap
	//    (820px) keeps the panel inside typical screens; on shorter screens the
	//    canvas anchors (8%..92% vertically) clamp it further, and the body
	//    ScrollBox absorbs any remaining overflow so nothing is ever clipped.
	USizeBox* PanelSizer = WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass());
	PanelSizer->SetWidthOverride(640.f);
	PanelSizer->SetMaxDesiredWidth(640.f);
	PanelSizer->SetMaxDesiredHeight(820.f);
	PanelSizer->SetVisibility(ESlateVisibility::Visible);
	if (UCanvasPanelSlot* PanelSlot = Cast<UCanvasPanelSlot>(Root->AddChild(PanelSizer)))
	{
		// Anchor to a centered vertical band (8%..92%) so the panel can never be
		// taller than ~84% of the viewport, and center it horizontally.
		PanelSlot->SetAnchors(FAnchors(0.5f, 0.08f, 0.5f, 0.92f));
		PanelSlot->SetAlignment(FVector2D(0.5f, 0.f));
		// Left offset = -half width (centering); width comes from the SizeBox.
		// Top/Bottom offsets are honoured because the anchors span vertically.
		PanelSlot->SetOffsets(FMargin(0.f, 0.f, 640.f, 0.f));
		PanelSlot->SetAutoSize(false);
		PanelSlot->SetZOrder(1);
	}

	UBorder* Panel = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
	{
		FSlateBrush PanelBrush;
		PanelBrush.TintColor = FSlateColor(PanelFill);
		PanelBrush.DrawAs = ESlateBrushDrawType::RoundedBox;
		PanelBrush.OutlineSettings.CornerRadii = FVector4(12.f, 12.f, 12.f, 12.f);
		PanelBrush.OutlineSettings.RoundingType = ESlateBrushRoundingType::FixedRadius;
		PanelBrush.OutlineSettings.Width = 1.f;
		PanelBrush.OutlineSettings.Color = FSlateColor(Accent.CopyWithNewOpacity(0.45f));
		Panel->SetBrush(PanelBrush);
	}
	Panel->SetPadding(FMargin(0.f));            // inner padding handled per-region
	Panel->SetHorizontalAlignment(HAlign_Fill);
	Panel->SetVerticalAlignment(VAlign_Fill);
	Panel->SetVisibility(ESlateVisibility::Visible);
	PanelSizer->AddChild(Panel);

	// Outer vertical layout: [pinned header] [Fill scrolling body] [pinned footer].
	// Only the middle region scrolls, so the title and RESUME stay on screen.
	UVerticalBox* Outer = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass());
	Panel->AddChild(Outer);

	// ── PINNED HEADER ───────────────────────────────────────────────────────────
	UVerticalBox* Header = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass());
	{
		auto AddToHeader = [&](UWidget* W, float TopPad) -> UVerticalBoxSlot*
		{
			UVerticalBoxSlot* S = Cast<UVerticalBoxSlot>(Header->AddChild(W));
			if (S) { S->SetPadding(FMargin(0.f, TopPad, 0.f, 0.f)); }
			return S;
		};

		UTextBlock* Title = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass());
		Title->SetText(FText::FromString(TEXT("MAIA DETECTOR CONCEPT")));
		{
			FSlateFontInfo TitleFont = MakeFont(30, true);
			TitleFont.LetterSpacing = 220;
			Title->SetFont(TitleFont);
			Title->SetColorAndOpacity(FSlateColor(NearWhite));
		}
		AddToHeader(Title, 0.f);

		// Credit line: muted text + clickable link button.
		UHorizontalBox* CreditRow = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());

		UTextBlock* Credit = MakeLabel(TEXT("Lawrence Lee · University of Tennessee · "), 12, MutedGrey);
		if (UHorizontalBoxSlot* CS = Cast<UHorizontalBoxSlot>(CreditRow->AddChild(Credit)))
		{
			CS->SetVerticalAlignment(VAlign_Center);
		}

		UButton* Link = MakeButton(TEXT("muoncollider.us"), 12, FLinearColor(0.f, 0.f, 0.f, 0.f), Accent.CopyWithNewOpacity(0.18f), Accent);
		Link->OnClicked.AddDynamic(this, &UColliderVisOptionsWidget::OnCreditLinkClicked);
		if (UHorizontalBoxSlot* LS = Cast<UHorizontalBoxSlot>(CreditRow->AddChild(Link)))
		{
			LS->SetVerticalAlignment(VAlign_Center);
		}
		AddToHeader(CreditRow, 6.f);

		// Thin accent rule separating the pinned header from the scrolling body.
		UBorder* Rule = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
		Rule->SetBrushColor(Accent.CopyWithNewOpacity(0.7f));
		USizeBox* RuleSizer = WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass());
		RuleSizer->SetHeightOverride(2.f);
		RuleSizer->AddChild(Rule);
		AddToHeader(RuleSizer, 14.f);
	}
	if (UVerticalBoxSlot* HS = Cast<UVerticalBoxSlot>(Outer->AddChild(Header)))
	{
		HS->SetPadding(FMargin(32.f, 28.f, 32.f, 0.f));
		HS->SetSize(FSlateChildSize(ESlateSizeRule::Automatic));
	}

	// ── SCROLLING BODY ──────────────────────────────────────────────────────────
	// Everything between the header and footer lives inside this ScrollBox so any
	// overflow scrolls instead of being clipped off-screen.
	UScrollBox* Body = WidgetTree->ConstructWidget<UScrollBox>(UScrollBox::StaticClass());
	Body->SetScrollBarVisibility(ESlateVisibility::Visible);
	Body->SetAnimateWheelScrolling(true);
	Body->SetVisibility(ESlateVisibility::Visible);
	if (UVerticalBoxSlot* BS = Cast<UVerticalBoxSlot>(Outer->AddChild(Body)))
	{
		BS->SetSize(FSlateChildSize(ESlateSizeRule::Fill));   // takes remaining height
		BS->SetPadding(FMargin(32.f, 4.f, 24.f, 4.f));        // right pad leaves room for scrollbar
	}

	// All body sections are stacked in this VerticalBox, which is the ScrollBox's
	// single child.
	UVerticalBox* Stack = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass());
	if (UScrollBoxSlot* StackSlot = Cast<UScrollBoxSlot>(Body->AddChild(Stack)))
	{
		StackSlot->SetHorizontalAlignment(HAlign_Fill);
	}

	auto AddToStack = [&](UWidget* W, float TopPad) -> UVerticalBoxSlot*
	{
		UVerticalBoxSlot* S = Cast<UVerticalBoxSlot>(Stack->AddChild(W));
		if (S) { S->SetPadding(FMargin(0.f, TopPad, 0.f, 0.f)); }
		return S;
	};

	// ── DETECTOR SYSTEMS ────────────────────────────────────────────────────────
	AddToStack(MakeSectionHeader(TEXT("Detector Systems")), 18.f);

	// Show All / Hide All row.
	{
		UHorizontalBox* AllRow = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());

		UButton* ShowAll = MakeButton(TEXT("Show All"), 13, BtnNormal, BtnHover, NearWhite);
		ShowAll->OnClicked.AddDynamic(this, &UColliderVisOptionsWidget::OnShowAllClicked);
		if (UHorizontalBoxSlot* S = Cast<UHorizontalBoxSlot>(AllRow->AddChild(ShowAll)))
		{
			S->SetPadding(FMargin(0.f, 0.f, 8.f, 0.f));
		}

		UButton* HideAll = MakeButton(TEXT("Hide All"), 13, BtnNormal, BtnHover, NearWhite);
		HideAll->OnClicked.AddDynamic(this, &UColliderVisOptionsWidget::OnHideAllClicked);
		AllRow->AddChild(HideAll);

		AddToStack(AllRow, 10.f);
	}

	// Sub-detector rows. These live directly in the body stack (the whole body is
	// already inside a ScrollBox), so the list grows naturally and scrolls with the
	// rest of the content — no nested scroll region to fight the wheel.
	{
		UVerticalBox* DetList = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass());

		DetectorCheckBoxes.Reset();
		DetectorNames.Reset();

		const TArray<FSubDetectorEntry> SubDetectors = GetSubDetectorList();
		for (const FSubDetectorEntry& Entry : SubDetectors)
		{
			UHorizontalBox* DetRow = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());

			// Color swatch.
			USizeBox* SwatchSizer = WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass());
			SwatchSizer->SetWidthOverride(14.f);
			SwatchSizer->SetHeightOverride(14.f);
			UBorder* Swatch = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
			Swatch->SetBrushColor(Entry.LabelColor);
			SwatchSizer->AddChild(Swatch);
			if (UHorizontalBoxSlot* Sw = Cast<UHorizontalBoxSlot>(DetRow->AddChild(SwatchSizer)))
			{
				Sw->SetVerticalAlignment(VAlign_Center);
				Sw->SetPadding(FMargin(0.f, 0.f, 10.f, 0.f));
			}

			// Name.
			UTextBlock* NameText = MakeLabel(Entry.Name.ToString(), 15, BodyGrey);
			if (UHorizontalBoxSlot* NS = Cast<UHorizontalBoxSlot>(DetRow->AddChild(NameText)))
			{
				NS->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
				NS->SetVerticalAlignment(VAlign_Center);
			}

			// Toggle initialized from current visibility.
			UCheckBox* Toggle = WidgetTree->ConstructWidget<UCheckBox>(UCheckBox::StaticClass());
			const bool bVisible = GetSubDetectorVisible(Entry.Name);
			Toggle->SetCheckedState(bVisible ? ECheckBoxState::Checked : ECheckBoxState::Unchecked);
			Toggle->OnCheckStateChanged.AddDynamic(this, &UColliderVisOptionsWidget::OnDetectorToggleChangedDispatch);
			if (UHorizontalBoxSlot* TS = Cast<UHorizontalBoxSlot>(DetRow->AddChild(Toggle)))
			{
				TS->SetVerticalAlignment(VAlign_Center);
				TS->SetHorizontalAlignment(HAlign_Right);
			}

			DetectorCheckBoxes.Add(Toggle);
			DetectorNames.Add(Entry.Name);

			if (UVerticalBoxSlot* RowSlot = Cast<UVerticalBoxSlot>(DetList->AddChild(DetRow)))
			{
				RowSlot->SetPadding(FMargin(0.f, 4.f));
			}
		}

		AddToStack(DetList, 10.f);
	}

	// ── BEAM CUTAWAY ────────────────────────────────────────────────────────────
	// Four checkboxes mirror the 1-4 number keys: checked = that phi quadrant is cut
	// away = the matching CutQuad<i> wedge actor hidden (same actors the 1-4 keys toggle).
	AddToStack(MakeSectionHeader(TEXT("Beam Cutaway")), 18.f);
	{
		CutawayCheckBoxes.Reset();
		UWorld* W = GetWorld();
		for (int32 i = 0; i < 4; ++i)
		{
			bool bHidden = false;
			if (W)
			{
				TArray<AActor*> Found;
				UGameplayStatics::GetAllActorsWithTag(W, FName(*FString::Printf(TEXT("CutQuad%d"), i)), Found);
				if (Found.Num() > 0 && Found[0]->GetRootComponent())
					bHidden = !Found[0]->GetRootComponent()->IsVisible();
			}
			UCheckBox* CB = nullptr;
			UHorizontalBox* Row = MakeFeatureRow(
				FString::Printf(TEXT("Cut quadrant %d"), i + 1), bHidden, CB);
			if (CB)
			{
				CB->OnCheckStateChanged.AddDynamic(
					this, &UColliderVisOptionsWidget::OnCutawayToggleChangedDispatch);
				CutawayCheckBoxes.Add(CB);
			}
			AddToStack(Row, 6.f);
		}
	}

	// ── SETTINGS ────────────────────────────────────────────────────────────────
	AddToStack(MakeSectionHeader(TEXT("Settings")), 26.f);

	UColliderVisUserSettings* Settings = UColliderVisUserSettings::Get();

	// Mouse sensitivity slider.
	{
		UHorizontalBox* SensHeader = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());
		UTextBlock* SensLbl = MakeLabel(TEXT("Mouse Sensitivity"), 15, BodyGrey);
		if (UHorizontalBoxSlot* HS = Cast<UHorizontalBoxSlot>(SensHeader->AddChild(SensLbl)))
		{
			HS->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
			HS->SetVerticalAlignment(VAlign_Center);
		}
		const float InitSens = Settings ? Settings->GetLookSensitivity() : 0.15f;
		SensitivityValueText = MakeLabel(FString::Printf(TEXT("%.2f"), InitSens), 14, Accent);
		if (UHorizontalBoxSlot* VS = Cast<UHorizontalBoxSlot>(SensHeader->AddChild(SensitivityValueText)))
		{
			VS->SetVerticalAlignment(VAlign_Center);
			VS->SetHorizontalAlignment(HAlign_Right);
		}
		AddToStack(SensHeader, 12.f);

		SensitivitySlider = WidgetTree->ConstructWidget<USlider>(USlider::StaticClass());
		SensitivitySlider->SetMinValue(0.05f);
		SensitivitySlider->SetMaxValue(10.f);
		SensitivitySlider->SetValue(InitSens);
		SensitivitySlider->SetSliderHandleColor(Accent);
		SensitivitySlider->SetSliderBarColor(FLinearColor(0.15f, 0.18f, 0.22f, 1.f));
		SensitivitySlider->OnValueChanged.AddDynamic(this, &UColliderVisOptionsWidget::OnSensitivityChanged);
		AddToStack(SensitivitySlider, 6.f);
	}

	// Quality preset row.
	{
		AddToStack(MakeLabel(TEXT("Quality"), 15, BodyGrey), 16.f);

		UHorizontalBox* QRow = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());
		QualityButtons.Reset();

		const TCHAR* Names[5] = { TEXT("Low"), TEXT("Medium"), TEXT("High"), TEXT("Epic"), TEXT("Cinematic") };
		static const FName HandlerNames[5] = {
			FName("OnQuality0Clicked"), FName("OnQuality1Clicked"), FName("OnQuality2Clicked"),
			FName("OnQuality3Clicked"), FName("OnQuality4Clicked") };

		for (int32 q = 0; q < 5; ++q)
		{
			UButton* QB = MakeButton(Names[q], 12, BtnNormal, BtnHover, NearWhite);
			FScriptDelegate Del;
			Del.BindUFunction(this, HandlerNames[q]);
			QB->OnClicked.Add(Del);

			QualityButtons.Add(QB);
			if (UHorizontalBoxSlot* QS = Cast<UHorizontalBoxSlot>(QRow->AddChild(QB)))
			{
				QS->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
				QS->SetPadding(FMargin(q == 0 ? 0.f : 4.f, 0.f, 0.f, 0.f));
			}
		}
		AddToStack(QRow, 6.f);
		RefreshQualityButtons();
	}

	// Resolution preset row.
	{
		AddToStack(MakeLabel(TEXT("Resolution"), 15, BodyGrey), 16.f);

		UHorizontalBox* RRow = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());
		ResolutionButtons.Reset();

		const TCHAR* RNames[5] = { TEXT("720p"), TEXT("1080p"), TEXT("1440p"), TEXT("4K"), TEXT("Fullscreen") };
		static const FName RHandlers[5] = {
			FName("OnRes0Clicked"), FName("OnRes1Clicked"), FName("OnRes2Clicked"),
			FName("OnRes3Clicked"), FName("OnFullscreenClicked") };

		for (int32 r = 0; r < 5; ++r)
		{
			UButton* RB = MakeButton(RNames[r], 12, BtnNormal, BtnHover, NearWhite);
			FScriptDelegate Del;
			Del.BindUFunction(this, RHandlers[r]);
			RB->OnClicked.Add(Del);
			ResolutionButtons.Add(RB);
			if (UHorizontalBoxSlot* RS = Cast<UHorizontalBoxSlot>(RRow->AddChild(RB)))
			{
				RS->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
				RS->SetPadding(FMargin(r == 0 ? 0.f : 4.f, 0.f, 0.f, 0.f));
			}
		}
		AddToStack(RRow, 6.f);
	}

	// Feature toggles.
	{
		AddToStack(MakeSectionHeader(TEXT("Visual Features")), 22.f);

		UVerticalBox* Features = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass());

		auto AddFeature = [&](const FString& Label, bool bInit) -> UCheckBox*
		{
			UCheckBox* CB = nullptr;
			UHorizontalBox* Row = MakeFeatureRow(Label, bInit, CB);
			Features->AddChild(Row);
			return CB;
		};

		const bool bHaveSettings = (Settings != nullptr);
		UCheckBox* CBLumen   = AddFeature(TEXT("Lumen Reflections"),    bHaveSettings ? Settings->GetLumenReflectionsEnabled()   : true);
		UCheckBox* CBFog     = AddFeature(TEXT("Volumetric Fog"),       bHaveSettings ? Settings->GetVolumetricFogEnabled()      : true);
		UCheckBox* CBMblur   = AddFeature(TEXT("Motion Blur"),          bHaveSettings ? Settings->GetMotionBlurEnabled()         : true);
		UCheckBox* CBBloom   = AddFeature(TEXT("Bloom"),                bHaveSettings ? Settings->GetBloomEnabled()              : true);
		UCheckBox* CBDof     = AddFeature(TEXT("Depth of Field"),       bHaveSettings ? Settings->GetDepthOfFieldEnabled()       : true);
		UCheckBox* CBGrain   = AddFeature(TEXT("Film Grain"),           bHaveSettings ? Settings->GetFilmGrainEnabled()          : true);
		UCheckBox* CBShadows = AddFeature(TEXT("Screen-Space Shadows"), bHaveSettings ? Settings->GetScreenSpaceShadowsEnabled() : true);
		UCheckBox* CBNanite  = AddFeature(TEXT("Nanite"),               bHaveSettings ? Settings->GetNaniteEnabled()             : true);

		if (CBLumen)   CBLumen->OnCheckStateChanged.AddDynamic(this,   &UColliderVisOptionsWidget::OnLumenChanged);
		if (CBFog)     CBFog->OnCheckStateChanged.AddDynamic(this,     &UColliderVisOptionsWidget::OnVolumetricFogChanged);
		if (CBMblur)   CBMblur->OnCheckStateChanged.AddDynamic(this,   &UColliderVisOptionsWidget::OnMotionBlurChanged);
		if (CBBloom)   CBBloom->OnCheckStateChanged.AddDynamic(this,   &UColliderVisOptionsWidget::OnBloomChanged);
		if (CBDof)     CBDof->OnCheckStateChanged.AddDynamic(this,     &UColliderVisOptionsWidget::OnDepthOfFieldChanged);
		if (CBGrain)   CBGrain->OnCheckStateChanged.AddDynamic(this,   &UColliderVisOptionsWidget::OnFilmGrainChanged);
		if (CBShadows) CBShadows->OnCheckStateChanged.AddDynamic(this, &UColliderVisOptionsWidget::OnScreenSpaceShadowsChanged);
		if (CBNanite)  CBNanite->OnCheckStateChanged.AddDynamic(this,  &UColliderVisOptionsWidget::OnNaniteChanged);

		AddToStack(Features, 8.f);
	}

	// Bottom breathing room inside the scroll body so the last toggle isn't flush
	// against the footer divider when scrolled to the end.
	{
		USpacer* TailSpacer = WidgetTree->ConstructWidget<USpacer>(USpacer::StaticClass());
		TailSpacer->SetSize(FVector2D(1.f, 8.f));
		AddToStack(TailSpacer, 0.f);
	}

	// ── PINNED FOOTER ───────────────────────────────────────────────────────────
	// Lives in the Outer box (NOT the scroll body), so RESUME is always visible.
	{
		UVerticalBox* FooterWrap = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass());

		// Divider above the footer.
		UBorder* FootRule = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
		FootRule->SetBrushColor(Accent.CopyWithNewOpacity(0.30f));
		USizeBox* FootRuleSizer = WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass());
		FootRuleSizer->SetHeightOverride(1.f);
		FootRuleSizer->AddChild(FootRule);
		FooterWrap->AddChild(FootRuleSizer);

		UHorizontalBox* Footer = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass());

		UButton* Prev = MakeButton(TEXT("‹ Prev Event"), 13, BtnNormal, BtnHover, NearWhite);
		Prev->OnClicked.AddDynamic(this, &UColliderVisOptionsWidget::OnPrevEventClicked);
		if (UHorizontalBoxSlot* PS = Cast<UHorizontalBoxSlot>(Footer->AddChild(Prev)))
		{
			PS->SetPadding(FMargin(0.f, 0.f, 6.f, 0.f));
			PS->SetVerticalAlignment(VAlign_Center);
		}

		UButton* Next = MakeButton(TEXT("Next Event ›"), 13, BtnNormal, BtnHover, NearWhite);
		Next->OnClicked.AddDynamic(this, &UColliderVisOptionsWidget::OnNextEventClicked);
		if (UHorizontalBoxSlot* NS = Cast<UHorizontalBoxSlot>(Footer->AddChild(Next)))
		{
			NS->SetVerticalAlignment(VAlign_Center);
		}

		// Spacer pushes RESUME to the right.
		USpacer* Sp = WidgetTree->ConstructWidget<USpacer>(USpacer::StaticClass());
		Sp->SetSize(FVector2D(1.f, 1.f));
		if (UHorizontalBoxSlot* SpS = Cast<UHorizontalBoxSlot>(Footer->AddChild(Sp)))
		{
			SpS->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
		}

		// Prominent accent RESUME button.
		UButton* Resume = MakeButton(TEXT("RESUME"), 15, Accent.CopyWithNewOpacity(0.92f), NearWhite, FLinearColor(0.03f, 0.05f, 0.07f, 1.f));
		Resume->OnClicked.AddDynamic(this, &UColliderVisOptionsWidget::OnResumeClicked);
		if (UHorizontalBoxSlot* RS = Cast<UHorizontalBoxSlot>(Footer->AddChild(Resume)))
		{
			RS->SetVerticalAlignment(VAlign_Center);
		}

		if (UVerticalBoxSlot* FS = Cast<UVerticalBoxSlot>(FooterWrap->AddChild(Footer)))
		{
			FS->SetPadding(FMargin(0.f, 18.f, 0.f, 0.f));
		}

		if (UVerticalBoxSlot* FWS = Cast<UVerticalBoxSlot>(Outer->AddChild(FooterWrap)))
		{
			FWS->SetPadding(FMargin(32.f, 16.f, 32.f, 28.f));
			FWS->SetSize(FSlateChildSize(ESlateSizeRule::Automatic));
		}
	}

	return Super::RebuildWidget();
}

// ── Lifecycle ────────────────────────────────────────────────────────────────

void UColliderVisOptionsWidget::NativeConstruct()
{
	Super::NativeConstruct();

	DiscoverManagers();

	if (EventDisplayManager)
	{
		EventDisplayManager->OnEventLoaded.AddDynamic(this, &UColliderVisOptionsWidget::HandleEventLoaded);
		SyncEventState();
	}

	RefreshDetectorCheckBoxes();
	RefreshQualityButtons();
}

void UColliderVisOptionsWidget::DiscoverManagers()
{
	UWorld* World = GetWorld();
	if (!World) return;

	if (!EventDisplayManager)
	{
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(World, AEventDisplayManager::StaticClass(), Found);
		if (Found.Num() > 0)
		{
			EventDisplayManager = Cast<AEventDisplayManager>(Found[0]);
		}
	}

	if (!VisibilityManager)
	{
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(World, ADetectorVisibilityManager::StaticClass(), Found);
		if (Found.Num() > 0)
		{
			VisibilityManager = Cast<ADetectorVisibilityManager>(Found[0]);
		}
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

	FString StartDir = FPaths::GetPath(CurrentFilePath);

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

	for (const FSubDetectorEntry& Entry : VisibilityManager->Config->SubDetectors)
	{
		OnSubDetectorVisibilityChanged(Entry.Name, bVisible);
	}

	RefreshDetectorCheckBoxes();
}

void UColliderVisOptionsWidget::OnDetectorToggleChangedDispatch(bool /*bChecked*/)
{
	// UMG doesn't tell us WHICH checkbox changed, so reconcile every row: for any
	// toggle whose UI state differs from the managed visibility state, push the UI
	// state through. In practice exactly one row will have changed.
	for (int32 i = 0; i < DetectorCheckBoxes.Num() && i < DetectorNames.Num(); ++i)
	{
		UCheckBox* CB = DetectorCheckBoxes[i];
		if (!CB) continue;

		const bool bWantVisible = CB->IsChecked();
		if (GetSubDetectorVisible(DetectorNames[i]) != bWantVisible)
		{
			SetSubDetectorVisible(DetectorNames[i], bWantVisible);
		}
	}
}

void UColliderVisOptionsWidget::OnCutawayToggleChangedDispatch(bool /*bChecked*/)
{
	// Re-sync the four quadrant wedge actors (tag CutQuad0..3) from checkbox state:
	// checked = quadrant cut away = wedge actor hidden. Same actors the 1-4 keys toggle.
	UWorld* W = GetWorld();
	if (!W) return;
	for (int32 i = 0; i < CutawayCheckBoxes.Num() && i < 4; ++i)
	{
		UCheckBox* CB = CutawayCheckBoxes[i];
		if (!CB) continue;
		const bool bHide = CB->IsChecked();
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsWithTag(W, FName(*FString::Printf(TEXT("CutQuad%d"), i)), Found);
		for (AActor* A : Found)
			if (USceneComponent* RC = A->GetRootComponent())
				RC->SetVisibility(!bHide, /*bPropagateToChildren=*/true);
	}
}

void UColliderVisOptionsWidget::RefreshDetectorCheckBoxes()
{
	for (int32 i = 0; i < DetectorCheckBoxes.Num() && i < DetectorNames.Num(); ++i)
	{
		UCheckBox* CB = DetectorCheckBoxes[i];
		if (!CB) continue;
		const bool bVisible = GetSubDetectorVisible(DetectorNames[i]);
		CB->SetCheckedState(bVisible ? ECheckBoxState::Checked : ECheckBoxState::Unchecked);
	}
}

void UColliderVisOptionsWidget::RefreshOpenState()
{
	RefreshDetectorCheckBoxes();
	RefreshCutawayCheckBoxes();
}

void UColliderVisOptionsWidget::RefreshCutawayCheckBoxes()
{
	// Seed each checkbox from the matching quadrant wedge actor's hidden state
	// (hidden = cut away = checked). SetCheckedState does not broadcast, so this
	// won't re-fire the dispatch.
	UWorld* W = GetWorld();
	if (!W) return;
	for (int32 i = 0; i < CutawayCheckBoxes.Num() && i < 4; ++i)
	{
		UCheckBox* CB = CutawayCheckBoxes[i];
		if (!CB) continue;
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsWithTag(W, FName(*FString::Printf(TEXT("CutQuad%d"), i)), Found);
		const bool bHidden = (Found.Num() > 0 && Found[0]->GetRootComponent())
			? !Found[0]->GetRootComponent()->IsVisible() : false;
		CB->SetCheckedState(bHidden ? ECheckBoxState::Checked : ECheckBoxState::Unchecked);
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

// ── Click / value handlers ──────────────────────────────────────────────────

void UColliderVisOptionsWidget::OnResumeClicked()     { RequestClose(); }
void UColliderVisOptionsWidget::OnNextEventClicked()  { RequestNextEvent(); }
void UColliderVisOptionsWidget::OnPrevEventClicked()  { RequestPreviousEvent(); }

void UColliderVisOptionsWidget::OnShowAllClicked()    { SetAllSubDetectorsVisible(true); }
void UColliderVisOptionsWidget::OnHideAllClicked()    { SetAllSubDetectorsVisible(false); }

void UColliderVisOptionsWidget::OnCreditLinkClicked()
{
	UKismetSystemLibrary::LaunchURL(TEXT("https://muoncollider.us"));
}

void UColliderVisOptionsWidget::OnSensitivityChanged(float Value)
{
	if (UColliderVisUserSettings* Settings = UColliderVisUserSettings::Get())
	{
		Settings->SetLookSensitivity(Value);
	}

	// Also push to the owning pawn if it's a ColliderVis character.
	if (APlayerController* PC = GetOwningPlayer())
	{
		if (AColliderVisCharacter* Char = Cast<AColliderVisCharacter>(PC->GetPawn()))
		{
			Char->SetLookSensitivity(Value);
		}
	}

	if (SensitivityValueText)
	{
		SensitivityValueText->SetText(FText::FromString(FString::Printf(TEXT("%.2f"), Value)));
	}
}

void UColliderVisOptionsWidget::ApplyQualityPreset(int32 Preset)
{
	if (UColliderVisUserSettings* Settings = UColliderVisUserSettings::Get())
	{
		Settings->SetQualityPreset(Preset);
	}
	RefreshQualityButtons();
}

void UColliderVisOptionsWidget::RefreshQualityButtons()
{
	int32 Active = 3;
	if (UColliderVisUserSettings* Settings = UColliderVisUserSettings::Get())
	{
		Active = Settings->GetQualityPreset();
	}

	for (int32 q = 0; q < QualityButtons.Num(); ++q)
	{
		UButton* Btn = QualityButtons[q];
		if (!Btn) continue;

		const bool bActive = (q == Active);
		FButtonStyle Style = Btn->GetStyle();

		FSlateBrush Normal = Style.Normal;
		Normal.TintColor = FSlateColor(bActive ? Accent.CopyWithNewOpacity(0.9f) : BtnNormal);
		Style.SetNormal(Normal);

		FSlateBrush Pressed = Style.Pressed;
		Pressed.TintColor = FSlateColor(bActive ? Accent : BtnHover * 0.8f);
		Style.SetPressed(Pressed);

		Btn->SetStyle(Style);

		// Active button text -> dark for contrast against the accent fill.
		if (Btn->GetChildrenCount() > 0)
		{
			if (UTextBlock* Txt = Cast<UTextBlock>(Btn->GetChildAt(0)))
			{
				Txt->SetColorAndOpacity(FSlateColor(bActive ? FLinearColor(0.03f, 0.05f, 0.07f, 1.f) : NearWhite));
			}
		}
	}
}

void UColliderVisOptionsWidget::OnQuality0Clicked() { ApplyQualityPreset(0); }
void UColliderVisOptionsWidget::OnQuality1Clicked() { ApplyQualityPreset(1); }
void UColliderVisOptionsWidget::OnQuality2Clicked() { ApplyQualityPreset(2); }
void UColliderVisOptionsWidget::OnQuality3Clicked() { ApplyQualityPreset(3); }
void UColliderVisOptionsWidget::OnQuality4Clicked() { ApplyQualityPreset(4); }

void UColliderVisOptionsWidget::ApplyResolution(int32 W, int32 H)
{
	// Resolution changes only apply to a real standalone game window. In PIE/editor
	// ApplyResolutionSettings re-evaluates the viewport and asserts (crash), so skip
	// there — the setting is still meaningful when the project is run standalone.
	if (GIsEditor)
	{
		UE_LOG(LogTemp, Log, TEXT("Resolution change ignored in editor/PIE (applies in standalone)."));
		return;
	}
	if (UColliderVisUserSettings* Settings = UColliderVisUserSettings::Get())
	{
		Settings->SetScreenResolution(FIntPoint(W, H));
		Settings->ApplyResolutionSettings(false);
		Settings->SaveSettings();
	}
}

void UColliderVisOptionsWidget::OnRes0Clicked() { ApplyResolution(1280, 720); }
void UColliderVisOptionsWidget::OnRes1Clicked() { ApplyResolution(1920, 1080); }
void UColliderVisOptionsWidget::OnRes2Clicked() { ApplyResolution(2560, 1440); }
void UColliderVisOptionsWidget::OnRes3Clicked() { ApplyResolution(3840, 2160); }

void UColliderVisOptionsWidget::OnFullscreenClicked()
{
	if (GIsEditor)
	{
		UE_LOG(LogTemp, Log, TEXT("Fullscreen toggle ignored in editor/PIE (applies in standalone)."));
		return;
	}
	if (UColliderVisUserSettings* Settings = UColliderVisUserSettings::Get())
	{
		const EWindowMode::Type Cur = Settings->GetFullscreenMode();
		const EWindowMode::Type Next =
			(Cur == EWindowMode::Windowed) ? EWindowMode::WindowedFullscreen : EWindowMode::Windowed;
		Settings->SetFullscreenMode(Next);
		Settings->ApplyResolutionSettings(false);
		Settings->SaveSettings();
	}
}

void UColliderVisOptionsWidget::OnLumenChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetLumenReflectionsEnabled(bChecked);
}
void UColliderVisOptionsWidget::OnVolumetricFogChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetVolumetricFogEnabled(bChecked);
}
void UColliderVisOptionsWidget::OnMotionBlurChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetMotionBlurEnabled(bChecked);
}
void UColliderVisOptionsWidget::OnBloomChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetBloomEnabled(bChecked);
}
void UColliderVisOptionsWidget::OnDepthOfFieldChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetDepthOfFieldEnabled(bChecked);
}
void UColliderVisOptionsWidget::OnFilmGrainChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetFilmGrainEnabled(bChecked);
}
void UColliderVisOptionsWidget::OnScreenSpaceShadowsChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetScreenSpaceShadowsEnabled(bChecked);
}
void UColliderVisOptionsWidget::OnNaniteChanged(bool bChecked)
{
	if (UColliderVisUserSettings* S = UColliderVisUserSettings::Get()) S->SetNaniteEnabled(bChecked);
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
