import unreal
for n in ["GeometryScript_NewAssetUtils", "GeometryScript_AssetUtils"]:
    cls = getattr(unreal, n, None)
    if cls:
        unreal.log_warning("M %s -> %s" % (n, [m for m in dir(cls) if "static" in m or "create" in m]))
o = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
unreal.log_warning("OPTS %s" % [p for p in dir(o) if not p.startswith("_")][:40])
