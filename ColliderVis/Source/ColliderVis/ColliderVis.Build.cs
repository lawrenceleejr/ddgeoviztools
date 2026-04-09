using UnrealBuildTool;

public class ColliderVis : ModuleRules
{
	public ColliderVis(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"UMG",
			"Json",
			"JsonUtilities",
			"ProceduralMeshComponent",
			"HeadMountedDisplay",   // IXRTrackingSystem
			"XRBase"                // UMotionControllerComponent
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"Slate",
			"SlateCore"
		});

		// Native OS file picker for the options menu (not available on Android/Quest)
		if (Target.Platform != UnrealTargetPlatform.Android)
		{
			PrivateDependencyModuleNames.Add("DesktopPlatform");
		}
	}
}
