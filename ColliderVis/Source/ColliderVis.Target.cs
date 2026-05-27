using UnrealBuildTool;

public class ColliderVisTarget : TargetRules
{
	public ColliderVisTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		// V6 build settings (UE 5.7+ default) + Latest include-order rules:
		// V6 turns on UndefinedIdentifierWarningLevel=Error and a few other
		// strict checks.  Required when sharing build products with the
		// standard UnrealEditor binaries (which themselves are built with V6),
		// otherwise UBT refuses to mix differing setting values across
		// modules that link together.
		DefaultBuildSettings = BuildSettingsVersion.V6;
		IncludeOrderVersion  = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("ColliderVis");
	}
}
