using UnrealBuildTool;

public class ColliderVisEditorTarget : TargetRules
{
	public ColliderVisEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		// See ColliderVis.Target.cs for the rationale behind these values —
		// the editor and game targets share their build-settings version.
		// V6 is required when sharing UnrealEditor binaries on UE 5.7+;
		// V5 mixed with the engine's V6 settings triggers "modifies the
		// values of properties: UndefinedIdentifierWarningLevel" from UBT.
		DefaultBuildSettings = BuildSettingsVersion.V6;
		IncludeOrderVersion  = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("ColliderVis");
	}
}
