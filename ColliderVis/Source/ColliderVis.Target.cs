using UnrealBuildTool;

public class ColliderVisTarget : TargetRules
{
	public ColliderVisTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		// V5 build settings + Latest include-order rules: lets UBT pick the
		// most current IWYU enforcement available in the engine compiling
		// this project (works on UE 5.5, 5.6, 5.7+).  If a strict IWYU
		// failure shows up after an engine upgrade, pin to a specific value
		// like `EngineIncludeOrderVersion.Unreal5_5` instead.
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion  = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("ColliderVis");
	}
}
