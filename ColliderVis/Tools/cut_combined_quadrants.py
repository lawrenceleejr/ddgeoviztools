"""
cut_combined_quadrants.py — cut the merged detector+accelerator mesh into 4 phi
quadrant wedges so each can be toggled (visibility) by the keys/menu.

Prereq: SceneTools.merge_actors already produced /Game/Detector/Cut/CombinedDetector
(one StaticMeshActor 'CombinedDetector' + mesh /Game/Detector/Cut/Combined).

For each quadrant q in 0..3 (phi = atan2(worldZ, worldX), beam axis = world Y):
  - copy the combined mesh into a DynamicMesh,
  - plane-cut twice (boundary half-planes through the Y axis at q*90 and (q+1)*90),
  - bake to /Game/Detector/Cut/Quad_q<N>, spawn actor 'CutQuad<N>' (tag CutQuad<N>,
    M_DetectorGeometry, NoCollision).
Then hide the 70 original Detector_*/AccelMag_*/AccelBeamPipe actors AND the merged
CombinedDetector actor (the wedge pieces replace them).

VERBOSE: logs full tracebacks (no swallowing) so failures are diagnosable.

Run headless (editor closed):
    UnrealEditor-Cmd <proj>/ColliderVis.uproject -run=pythonscript -script=<this>
"""
import json
import math
import traceback
import unreal

LEVEL = "/Game/Maps/ColliderVisMain"
OUT_DIR = "/Game/Detector/Cut"
# Two SEPARATE cut jobs so each gets the right treatment:
#  - DETECTOR (SM_Det): simplify the full ~1.27M-tri mesh to ~480k and cut with the
#    plane-cut's OWN hole-fill only — leaves it exactly as it was (clean shells, no
#    extra capping, no tri blow-up).
#  - ACCELERATOR (SM_Acc): low-poly solid magnet cylinders; no simplify, but cap ALL
#    open boundaries (fill_all_mesh_holes) + recompute normals so the cut magnet ends
#    are closed solids instead of hollow openings.
JOBS = [
    {"mesh": "/Game/Detector/Cut/SM_Acc2", "out": "Quad_acc_q", "simplify": None,   "method": "box"},
]

# Each phi-quadrant is an axis-aligned quarter-space about the beam (Y) axis:
#   q0 +X+Z, q1 -X+Z, q2 -X-Z, q3 +X-Z.  (cx, cz) = sign of the box centre per quadrant.
_QUAD_SIGN = [(1, 1), (-1, 1), (-1, -1), (1, -1)]


def _cut_frame(theta_deg, keep_plus_phi):
    """Transform whose Z axis is the plane normal. Half-plane through the Y axis at
    angle theta (from +X toward +Z): in-plane dir d=(cos,0,sin); normal n=(sin,0,-cos).
    keep_plus_phi flips the normal so ApplyMeshPlaneCut keeps the wanted side."""
    t = math.radians(theta_deg)
    n = unreal.Vector(math.sin(t), 0.0, -math.cos(t))
    if not keep_plus_phi:
        n = unreal.Vector(-n.x, -n.y, -n.z)
    rot = unreal.MathLibrary.make_rot_from_z(n)
    try:
        quat = rot.quaternion()
    except Exception:
        quat = unreal.MathLibrary.conv_rotator_to_quaternion(rot)
    xf = unreal.Transform()
    xf.translation = unreal.Vector(0, 0, 0)
    xf.rotation = quat
    xf.scale3d = unreal.Vector(1, 1, 1)
    return xf


def _src_mats(sm):
    """The mesh's per-slot MaterialInterfaces, in slot order."""
    mats = []
    try:
        for s in sm.get_editor_property("static_materials"):
            mats.append(s.get_editor_property("material_interface"))
    except Exception:
        i = 0
        while True:
            m = sm.get_material(i)
            if m is None:
                break
            mats.append(m); i += 1
    return mats


def _cut_job(job, pool, res):
    sm = unreal.EditorAssetLibrary.load_asset(job["mesh"])
    if sm is None:
        res["errors"].append("missing %s" % job["mesh"])
        unreal.log_warning("CUT: missing mesh %s" % job["mesh"]); return
    src_mats = _src_mats(sm)
    unreal.log_warning("CUT[%s]: %d material slots" % (job["out"], len(src_mats)))

    base = pool.request_mesh()
    asset_opts = unreal.GeometryScriptCopyMeshFromAssetOptions()
    lod = unreal.GeometryScriptMeshReadLOD(); lod.lod_index = 0
    base, _oc = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(sm, base, asset_opts, lod)
    if job["simplify"]:
        try:
            simp_opts = unreal.GeometryScriptSimplifyMeshOptions()
            unreal.GeometryScript_MeshSimplification.apply_simplify_to_triangle_count(
                base, int(job["simplify"]), simp_opts)
            unreal.log_warning("CUT[%s]: simplified base to ~%d tris" % (job["out"], job["simplify"]))
        except Exception as e:
            unreal.log_warning("CUT[%s]: simplify FAILED %s" % (job["out"], repr(e))); traceback.print_exc()

    for q in range(4):
        try:
            dm = pool.request_mesh()
            unreal.GeometryScript_MeshDecomposition.copy_mesh_to_mesh(base, dm)

            if job["method"] == "box":
                # Robust capped cut for the solid magnet cylinders: INTERSECT with a
                # big box occupying this quadrant's quarter-space. Boolean of two closed
                # solids is itself closed -> the cut faces are capped, no open shells,
                # no z-fighting (unlike plane-cut + hole-fill on merged shells).
                BIG = 12000.0; LEN = 130000.0
                cx, cz = _QUAD_SIGN[q]
                box = pool.request_mesh()
                prim_opts = unreal.GeometryScriptPrimitiveOptions()
                box_xf = unreal.Transform()
                box_xf.translation = unreal.Vector(cx * BIG / 2.0, 0.0, cz * BIG / 2.0)
                unreal.GeometryScript_Primitives.append_box(box, prim_opts, box_xf, BIG, LEN, BIG)
                bopts = unreal.GeometryScriptMeshBooleanOptions()
                try: bopts.fill_holes = True
                except Exception: pass
                ident = unreal.Transform()
                unreal.GeometryScript_MeshBooleans.apply_mesh_boolean(
                    dm, ident, box, ident, unreal.GeometryScriptBooleanOperation.INTERSECTION, bopts)
                pool.return_mesh(box)
            else:
                cut_opts = unreal.GeometryScriptMeshPlaneCutOptions()
                try: cut_opts.fill_holes = True
                except Exception: pass
                unreal.GeometryScript_MeshBooleans.apply_mesh_plane_cut(dm, _cut_frame(q * 90.0, True), cut_opts)
                unreal.GeometryScript_MeshBooleans.apply_mesh_plane_cut(dm, _cut_frame((q + 1) * 90.0, False), cut_opts)

            pkg = "%s/%s%d" % (OUT_DIR, job["out"], q)
            new_opts = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
            try:
                new_opts.enable_nanite = False
                new_opts.enable_collision = False
            except Exception: pass
            new_sm, _o2 = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(dm, pkg, new_opts)
            if new_sm:
                for i, m in enumerate(src_mats):
                    if m is not None:
                        try: new_sm.set_material(i, m)
                        except Exception: pass
            unreal.EditorAssetLibrary.save_asset(pkg)
            pool.return_mesh(dm)
            res["quads"] += 1
            unreal.log_warning("CUT: built %s%d" % (job["out"], q))
        except Exception as e:
            res["errors"].append("%s%d: %s" % (job["out"], q, repr(e)))
            unreal.log_warning("CUT: %s%d FAILED: %s" % (job["out"], q, repr(e)))
            traceback.print_exc()


def run():
    # BUILD-ONLY: cut SM_Det + SM_Acc into 8 wedge assets (Quad_det_q0..3 + Quad_acc_q0..3).
    # No actor spawning here (it crashes the headless commandlet); placement is via MCP.
    res = {"quads": 0, "errors": []}
    pool = unreal.DynamicMeshPool()
    for job in JOBS:
        _cut_job(job, pool, res)
    try: unreal.EditorAssetLibrary.save_directory(OUT_DIR)
    except Exception: pass
    print("COLLIDERVIS_CUT=" + json.dumps(res))


if __name__ == "__main__":
    run()
