using UnrealBuildTool;

public class ColliderVisTarget : TargetRules
{
	public ColliderVisTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		// V7 build settings (UE 5.8+ default) + Latest include-order rules:
		// V7 turns on UnreachableCode/ReturnType/DanglingWarningLevel=Error and
		// a few other strict checks.  Required when sharing build products with
		// the standard UnrealEditor binaries (which themselves are built with
		// V7), otherwise UBT refuses to mix differing setting values across
		// modules that link together.
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion  = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("ColliderVis");
	}
}
