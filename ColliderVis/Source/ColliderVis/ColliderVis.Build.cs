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
			"CinematicCamera",
			"ProceduralMeshComponent",
			"HeadMountedDisplay",   // UMotionControllerComponent, IXRTrackingSystem
			"XRBase"                // FXRMotionControllerBase source IDs
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"Slate",
			"SlateCore"
		});
	}
}
