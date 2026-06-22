"""
build_quadrant_pieces.py — build real-geometry, toggleable phi-quadrant cutaway
pieces of the detector + accelerator.

A material/OpacityMask cutaway does NOT render in this project, so instead of
masking pixels we cut ACTUAL geometry into four 90-degree phi wedges and let C++
toggle their visibility by tag. This tool:

  1. Collects the ~70 source StaticMeshActors (labels starting with `Detector_`
     or `AccelMag_`, plus the single `AccelBeamPipe`). It deliberately does NOT
     touch AccelHall / CutawayWalkFloor / Floor_Ground / Hall_Sphere / etc.
  2. Appends every source StaticMesh, transformed into WORLD space by its actor
     transform, into one combined DynamicMesh (allocated from a DynamicMeshPool —
     the supported headless pattern).
  3. For each quadrant q in 0..3, duplicates the combined mesh and plane-cuts it
     TWICE (at q*90 and (q+1)*90 degrees) to keep only that 90-degree wedge,
     capping the cut faces. Writes the wedge to a new StaticMesh asset
     /Game/Detector/Cut/Quad_q<N> (Nanite OFF, LOD0 kept, material
     /Game/Materials/M_DetectorGeometry on every slot) and spawns a
     StaticMeshActor `CutQuad<N>` at the world origin, tagged `CutQuad<N>`,
     with NoCollision.
  4. Hides the ~70 originals (component visibility off + hidden-in-editor) so only
     the cut pieces render. Originals are NOT deleted — the reimport pipeline
     depends on them.
  5. Saves the level and /Game/Detector/Cut, then prints COLLIDERVIS_QUADRANTS=<json>.

Geometry / coordinate conventions (per spec):
  - Beam axis = world Y.
  - Quadrants are 90-degree wedges in the world X-Z plane around Y:
        phi = atan2(worldZ, worldX) in [0, 360);  q = floor(phi / 90).
  - A boundary half-plane at angle theta (from +X toward +Z) has in-plane
    direction (cos t, 0, sin t) and plane normal n(theta) = (sin t, 0, -cos t).
    Note n(theta) points to the -phi side (clockwise), so a point at phi slightly
    GREATER than theta has a NEGATIVE signed distance along n(theta).

Run headless (editor MUST be closed):
    UnrealEditor-Cmd <proj>/ColliderVis.uproject \
        -run=pythonscript -script="<proj>/Tools/build_quadrant_pieces.py"
"""
import json
import math
import traceback

import unreal

LEVEL = "/Game/Maps/ColliderVisMain"
CUT_DIR = "/Game/Detector/Cut"
MATERIAL_PATH = "/Game/Materials/M_DetectorGeometry"
NUM_QUADRANTS = 4


# ---------------------------------------------------------------------------
# Source-actor selection
# ---------------------------------------------------------------------------
def _is_source_label(lbl):
    return (
        lbl.startswith("Detector_")
        or lbl.startswith("AccelMag_")
        or lbl == "AccelBeamPipe"
    )


# ---------------------------------------------------------------------------
# Plane-cut frame construction
# ---------------------------------------------------------------------------
def _make_cut_frame(theta_deg, keep_plus_phi):
    """Build the CutFrame transform for apply_mesh_plane_cut.

    The cut plane passes through the WORLD ORIGIN. GeometryScript's plane cut
    keeps the side of the plane on the +Z axis of the supplied CutFrame
    transform (i.e. the frame's local +Z is the "keep" normal).

    A half-plane boundary at angle theta has geometric normal
        n(theta) = (sin t, 0, -cos t)
    which points toward the -phi (clockwise) side. A point whose phi is slightly
    GREATER than theta lies on the -n side; a point with phi slightly LESS than
    theta lies on the +n side.

    For quadrant [q*90, (q+1)*90]:
      * cut at theta1 = q*90 must keep the +phi side  -> keep normal = -n(theta1)
      * cut at theta2 = (q+1)*90 must keep the -phi side -> keep normal = +n(theta2)

    So `keep_plus_phi=True` (lower boundary) -> keep_normal = -n(theta);
       `keep_plus_phi=False` (upper boundary) -> keep_normal = +n(theta).

    SIGNATURE ASSUMPTION (verify on run): apply_mesh_plane_cut takes a
    `cut_frame` (unreal.Transform) and keeps geometry on the +Z side of that
    frame. We orient the frame's Z toward the keep-normal via FindLookAtRotation
    from origin toward the keep-normal point. If your build keeps the OPPOSITE
    side, flip `keep_plus_phi` handling (or negate keep_normal) — that is the one
    thing most likely to need a sign flip.
    """
    t = math.radians(theta_deg)
    # Geometric boundary normal n(theta), pointing to the -phi side.
    n = unreal.Vector(math.sin(t), 0.0, -math.cos(t))
    if keep_plus_phi:
        keep_normal = unreal.Vector(-n.x, -n.y, -n.z)  # keep +phi side
    else:
        keep_normal = unreal.Vector(n.x, n.y, n.z)      # keep -phi side

    origin = unreal.Vector(0.0, 0.0, 0.0)
    # Orient a transform whose +X looks along keep_normal, then we still need the
    # cut plane's normal to be the frame's local Z. MakeRotationFromZ is the most
    # direct: it yields a rotator whose local +Z aligns with keep_normal.
    # SIGNATURE ASSUMPTION: unreal.MathLibrary.make_rotation_from_z exists in 5.8;
    # if not, fall back to find_look_at_rotation (which aligns +X) and rotate.
    try:
        rot = unreal.MathLibrary.make_rotation_from_z(keep_normal)
    except Exception:
        # Fallback: align +X to keep_normal via look-at, then pitch so X->Z.
        look = unreal.MathLibrary.find_look_at_rotation(origin, keep_normal)
        rot = unreal.Rotator(look.pitch - 90.0, look.yaw, look.roll)

    return unreal.Transform(rot, origin, unreal.Vector(1.0, 1.0, 1.0))


# ---------------------------------------------------------------------------
# StaticMesh asset creation from a DynamicMesh
# ---------------------------------------------------------------------------
def _new_static_mesh_asset(asset_name):
    """Create (or recreate) an empty StaticMesh asset at CUT_DIR/asset_name."""
    pkg_path = "%s/%s" % (CUT_DIR, asset_name)
    if unreal.EditorAssetLibrary.does_asset_exist(pkg_path):
        unreal.EditorAssetLibrary.delete_asset(pkg_path)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.StaticMeshFactoryNew()
    sm = tools.create_asset(asset_name, CUT_DIR, unreal.StaticMesh, factory)
    return sm, pkg_path


def _assign_material_all_slots(sm, material):
    if material is None:
        return
    try:
        smats = sm.get_static_materials()
        if smats:
            for i in range(len(smats)):
                sm.set_material(i, material)
        else:
            # No slots yet — add one.
            sm.add_material(material)  # SIGNATURE ASSUMPTION: StaticMesh.add_material exists
    except Exception:
        unreal.log_warning("QUADRANT: could not assign material to %s" % sm.get_name())
        traceback.print_exc()


def _dynamic_mesh_to_static_mesh(dyn_mesh, sm):
    """Bake a DynamicMesh into a StaticMesh asset (LOD0), Nanite OFF."""
    opts = unreal.GeometryScriptCopyMeshToAssetOptions()
    # Keep it simple/robust: replace existing materials list, single LOD0.
    opts.enable_recompute_normals = False
    opts.enable_recompute_tangents = False
    opts.enable_remove_degenerates = True
    opts.replace_materials = False
    opts.new_nanite_settings = unreal.GeometryScriptNaniteOptions()
    opts.new_nanite_settings.enabled = False  # Nanite OFF
    opts.apply_nanite_settings = True

    target_lod = unreal.GeometryScriptMeshWriteLOD()
    target_lod.lod_index = 0

    # SIGNATURE ASSUMPTION: copy_mesh_to_static_mesh(from_dynamic_mesh,
    #   to_static_mesh_asset, options, target_lod, b_emit_transaction) -> (mesh, outcome)
    unreal.GeometryScript_StaticMesh.copy_mesh_to_static_mesh(
        dyn_mesh, sm, opts, target_lod, False
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run():
    result = {"sources": 0, "quads_built": 0, "hidden": 0, "errors": 0}

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.load_level(LEVEL)

    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    all_actors = eas.get_all_level_actors()

    sources = []
    for a in all_actors:
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        if _is_source_label(a.get_actor_label()):
            sources.append(a)
    result["sources"] = len(sources)
    unreal.log_warning("QUADRANT: collected %d source actors" % len(sources))

    if not sources:
        print("COLLIDERVIS_QUADRANTS=" + json.dumps(result))
        return result

    # Ensure the destination directory exists.
    if not unreal.EditorAssetLibrary.does_directory_exist(CUT_DIR):
        unreal.EditorAssetLibrary.make_directory(CUT_DIR)

    material = unreal.EditorAssetLibrary.load_asset(MATERIAL_PATH)
    if material is None:
        unreal.log_warning("QUADRANT: material %s not found; slots left default" % MATERIAL_PATH)

    pool = unreal.DynamicMeshPool()

    # -- Build the combined WORLD-space mesh ------------------------------------
    combined = pool.request_mesh()
    for a in sources:
        lbl = a.get_actor_label()
        try:
            smc = a.get_component_by_class(unreal.StaticMeshComponent)
            sm = smc.get_static_mesh() if smc else None
            if sm is None:
                unreal.log_warning("QUADRANT: %s has no static mesh; skipping" % lbl)
                result["errors"] += 1
                continue

            temp = pool.request_mesh()
            copy_opts = unreal.GeometryScriptCopyMeshFromAssetOptions()
            lod = unreal.GeometryScriptMeshReadLOD()
            lod.lod_index = 0
            # SIGNATURE ASSUMPTION: copy_mesh_from_static_mesh(from_static_mesh_asset,
            #   to_dynamic_mesh, asset_options, requested_lod) -> (mesh, outcome)
            unreal.GeometryScript_StaticMesh.copy_mesh_from_static_mesh(
                sm, temp, copy_opts, lod
            )

            world_xf = a.get_actor_transform()
            # Append temp transformed into world space, into the combined mesh.
            # SIGNATURE ASSUMPTION: append_mesh_transformed(target_mesh,
            #   append_mesh, append_transform, constant_transform=..., ...) -> mesh
            unreal.GeometryScript_MeshBasicEditFunctions.append_mesh_transformed(
                combined, temp, world_xf
            )
            pool.return_compute_mesh(temp)
        except Exception:  # noqa: BLE001
            result["errors"] += 1
            unreal.log_warning("QUADRANT: failed to copy/append %s" % lbl)
            traceback.print_exc()

    # -- Build each quadrant wedge ---------------------------------------------
    plane_opts = unreal.GeometryScriptMeshPlaneCutOptions()
    plane_opts.fill_holes = True          # cap the cut faces
    plane_opts.fill_spans = True
    # SIGNATURE ASSUMPTION: GeometryScriptMeshPlaneCutOptions has fill_holes/fill_spans
    # bools (UE5.8). If named differently, leave defaults (cut still works, faces open).

    for q in range(NUM_QUADRANTS):
        try:
            wedge = pool.request_mesh()
            # Duplicate the combined mesh into wedge.
            # SIGNATURE ASSUMPTION: copy_mesh_to_mesh(copy_from_mesh, copy_to_mesh)
            #   -> (copy_to_mesh, copy_from_mesh)
            unreal.GeometryScript_MeshBasicEditFunctions.copy_mesh_to_mesh(combined, wedge)

            theta1 = q * 90.0          # lower boundary: keep +phi side
            theta2 = (q + 1) * 90.0    # upper boundary: keep -phi side

            frame1 = _make_cut_frame(theta1, keep_plus_phi=True)
            frame2 = _make_cut_frame(theta2, keep_plus_phi=False)

            # SIGNATURE ASSUMPTION: apply_mesh_plane_cut(target_mesh, cut_frame,
            #   options) -> mesh
            unreal.GeometryScript_MeshBoolean.apply_mesh_plane_cut(wedge, frame1, plane_opts)
            unreal.GeometryScript_MeshBoolean.apply_mesh_plane_cut(wedge, frame2, plane_opts)

            asset_name = "Quad_q%d" % q
            sm, pkg_path = _new_static_mesh_asset(asset_name)
            _dynamic_mesh_to_static_mesh(wedge, sm)
            _assign_material_all_slots(sm, material)
            unreal.EditorAssetLibrary.save_asset(pkg_path, only_if_is_dirty=False)

            # Spawn the actor at the world origin (geometry already baked in world space).
            actor = eas.spawn_actor_from_object(
                sm, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
            )
            label = "CutQuad%d" % q
            actor.set_actor_label(label)
            actor.tags = [unreal.Name(label)]
            comp = actor.get_component_by_class(unreal.StaticMeshComponent)
            if comp:
                comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
                comp.set_collision_profile_name("NoCollision")

            pool.return_compute_mesh(wedge)
            result["quads_built"] += 1
            unreal.log_warning("QUADRANT: built %s (%s)" % (label, pkg_path))
        except Exception:  # noqa: BLE001
            result["errors"] += 1
            unreal.log_warning("QUADRANT: failed to build quadrant %d" % q)
            traceback.print_exc()

    pool.return_compute_mesh(combined)

    # -- Hide originals (do NOT delete) ----------------------------------------
    for a in sources:
        try:
            for c in a.get_components_by_class(unreal.StaticMeshComponent):
                c.set_visibility(False, True)  # propagate to children
            a.set_is_temporarily_hidden_in_editor(True)
            result["hidden"] += 1
        except Exception:  # noqa: BLE001
            result["errors"] += 1
            unreal.log_warning("QUADRANT: failed to hide %s" % a.get_actor_label())
            traceback.print_exc()

    # -- Save -------------------------------------------------------------------
    les.save_current_level()
    try:
        unreal.EditorAssetLibrary.save_directory(CUT_DIR, only_if_is_dirty=False)
    except Exception:
        traceback.print_exc()

    print("COLLIDERVIS_QUADRANTS=" + json.dumps(result))
    return result


if __name__ == "__main__":
    run()
