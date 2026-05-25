using UnrealBuildTool;

public class ColliderVisEditorTarget : TargetRules
{
	public ColliderVisEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		// See ColliderVis.Target.cs for the rationale behind these values —
		// the editor and game targets share their build-settings version.
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion  = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("ColliderVis");
	}
}
