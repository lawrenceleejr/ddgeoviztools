using UnrealBuildTool;

public class ColliderVisTarget : TargetRules
{
	public ColliderVisTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_4;
		ExtraModuleNames.Add("ColliderVis");
	}
}
