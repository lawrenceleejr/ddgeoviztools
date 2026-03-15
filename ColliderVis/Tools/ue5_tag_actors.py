"""
ue5_tag_actors.py — UE5 Editor Python script to tag imported static mesh actors.

Run from the UE5 Editor console:
    py /path/to/ColliderVis/Tools/ue5_tag_actors.py \
        --manifest /tmp/ue5_meshes/manifest.json \
        --content-path /Game/Detector

What it does:
1. Reads manifest.json (output of blend_to_ue5.py).
2. For each sub-detector, finds StaticMeshActors in the current level whose mesh asset
   name matches the sub-detector name.
3. Sets Actor Tags on each matching actor.
4. Enables Nanite on the static mesh asset.
5. Sets actor mobility to Static.

Requirements:
    Run inside UE5 Editor Python interpreter (Edit → Execute Python Script).
    Requires "Python Editor Script Plugin" enabled in the project.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest",     required=True,
                        help="Path to manifest.json from blend_to_ue5.py")
    parser.add_argument("--content-path", default="/Game/Detector",
                        help="UE5 content path where GLTF assets were imported")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    try:
        import unreal
    except ImportError:
        print("ERROR: 'unreal' module not available. Run this script inside the UE5 Editor.",
              file=sys.stderr)
        sys.exit(1)

    eal  = unreal.EditorActorSubsystem()
    eaul = unreal.EditorAssetLibrary()
    world = unreal.EditorLevelLibrary.get_editor_world()

    sub_detectors = manifest.get("sub_detectors", [])
    print(f"Processing {len(sub_detectors)} sub-detectors from manifest...")

    for entry in sub_detectors:
        name       = entry["name"]
        actor_tags = entry.get("actor_tags", [name])

        # Find the static mesh asset
        mesh_asset_path = f"{args.content_path}/{name}.{name}"
        mesh_asset = eaul.load_asset(mesh_asset_path)

        if mesh_asset and isinstance(mesh_asset, unreal.StaticMesh):
            # Enable Nanite
            mesh_asset.set_editor_property("nanite_settings",
                unreal.MeshNaniteSettings(enabled=True))
            eaul.save_asset(mesh_asset_path)
            print(f"  [{name}] Nanite enabled on {mesh_asset_path}")
        else:
            print(f"  [{name}] WARNING: Static mesh not found at {mesh_asset_path}")

        # Find placed actors in the current level whose mesh matches
        all_actors = eal.get_all_level_actors()
        matched = 0
        for actor in all_actors:
            if not isinstance(actor, unreal.StaticMeshActor):
                continue
            sm_comp = actor.static_mesh_component
            if sm_comp is None:
                continue
            sm = sm_comp.static_mesh
            if sm is None:
                continue

            asset_name = sm.get_name()
            if asset_name.lower() != name.lower():
                continue

            # Set actor tags
            existing_tags = list(actor.tags)
            for tag in actor_tags:
                if tag not in existing_tags:
                    existing_tags.append(tag)
            actor.tags = existing_tags

            # Set mobility to Static
            sm_comp.set_mobility(unreal.ComponentMobility.STATIC)

            # Disable collision (detector geometry is decorative)
            sm_comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)

            matched += 1

        print(f"  [{name}] Tagged {matched} actor(s) with tags {actor_tags}")

    print("\nDone. Save the level to persist actor tag changes.")


if __name__ == "__main__":
    main()
