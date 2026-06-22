using UnrealBuildTool;

public class ColliderVisEditorTarget : TargetRules
{
	public ColliderVisEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		// See ColliderVis.Target.cs for the rationale behind these values —
		// the editor and game targets share their build-settings version.
		// V7 is required when sharing UnrealEditor binaries on UE 5.8+;
		// an older version mixed with the engine's V7 settings triggers
		// "modifies the values of properties: UnreachableCode/ReturnType/
		// DanglingWarningLevel" from UBT.
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion  = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("ColliderVis");
	}
}
