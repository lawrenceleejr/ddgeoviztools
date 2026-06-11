extends RefCounted
## Loads sub-detector glTF files at runtime (no editor import step needed —
## works headless and from arbitrary directories) and assigns physically-based
## metal/crystal materials matched by sub-detector name.
##
## The palette mirrors src/gdml_to_blender.py so the Godot scene and the
## Blender renders stay visually consistent.

const MM_TO_M := 0.001

const DETECTOR_SHADER := "res://shaders/detector.gdshader"

## keyword list -> [base color, metallic, roughness]
const DETECTOR_MATERIALS := [
	[["ecal", "emcal", "em_cal", "crystal", "preshower", "pbwo4"],
		Color(0.35, 0.62, 0.52), 0.10, 0.35],
	[["hcal", "hcalo", "hadcal", "hcalorimeter"],
		Color(0.52, 0.38, 0.22), 0.70, 0.55],
	[["solenoid", "coil", "solen", "magnet_coil"],
		Color(0.72, 0.42, 0.22), 0.80, 0.45],
	[["yoke", "iron_yoke", "muon_iron", "flux_return"],
		Color(0.30, 0.28, 0.26), 0.75, 0.60],
	[["tracker", "trk", "sit", "svt", "ftd", "set", "etd", "tracking"],
		Color(0.22, 0.38, 0.60), 0.55, 0.50],
	[["tpc"], Color(0.78, 0.79, 0.80), 0.75, 0.50],
	[["pixel", "vxd", "vtx", "vertex", "velo", "pxd"],
		Color(0.28, 0.45, 0.72), 0.70, 0.45],
	[["muon", "mdt", "rpc", "tgc", "csc", "gem", "me0"],
		Color(0.55, 0.50, 0.68), 0.20, 0.70],
	[["tof", "btof", "rich", "dirc", "aerogel", "cherenkov", "pid"],
		Color(0.68, 0.58, 0.28), 0.65, 0.45],
	[["beampipe", "beam_pipe", "vacuumchamber", "bpipe"],
		Color(0.78, 0.79, 0.82), 0.80, 0.40],
	[["bch"], Color(0.55, 0.54, 0.53), 0.00, 0.95],
	[["nozzlew"], Color(0.26, 0.25, 0.24), 0.80, 0.55],
	[["nozzle", "tungsten", "shielding", "shield"],
		Color(0.28, 0.27, 0.25), 0.70, 0.65],
	[["calorimeter", "calo"], Color(0.42, 0.55, 0.38), 0.10, 0.75],
	[["support", "dead", "frame", "structure"],
		Color(0.40, 0.40, 0.42), 0.50, 0.70],
]

## Fallback palette, cycled when no keyword matches.
const FALLBACK_PALETTE := [
	[Color(0.65, 0.67, 0.70), 0.80, 0.45],  # steel
	[Color(0.58, 0.60, 0.63), 0.75, 0.55],  # brushed steel
	[Color(0.30, 0.32, 0.35), 0.70, 0.50],  # dark steel
	[Color(0.72, 0.55, 0.20), 0.80, 0.45],  # brass
	[Color(0.72, 0.40, 0.25), 0.80, 0.50],  # copper
	[Color(0.45, 0.45, 0.48), 0.00, 0.85],  # matte gray
	[Color(0.78, 0.79, 0.80), 0.80, 0.50],  # brushed aluminium
	[Color(0.55, 0.42, 0.15), 0.75, 0.50],  # dark brass
]

var _fallback_idx := 0


## Loads every .gltf/.glb in `dir`; returns { detector_name: Node3D }.
## Geometry is in mm (GDML convention) and gets scaled to metres.
func load_directory(dir: String) -> Dictionary:
	var out := {}
	var da := DirAccess.open(dir)
	if da == null:
		push_warning("DetectorLoader: cannot open directory '%s'" % dir)
		return out
	var files := {}
	for f in da.get_files():
		# In exported builds imported resources are listed with .remap /
		# .import suffixes; strip them to recover the logical file name.
		if f.ends_with(".remap") or f.ends_with(".import"):
			f = f.substr(0, f.rfind("."))
		var ext := f.get_extension().to_lower()
		if ext == "gltf" or ext == "glb":
			files[f] = true
	var names := files.keys()
	names.sort()
	for f in names:
		var det_name: String = f.get_basename()
		var node := _load_gltf(dir.path_join(f), det_name)
		if node != null:
			out[det_name] = node
	return out


func _load_gltf(path: String, det_name: String) -> Node3D:
	var scene: Node = null
	# Prefer the engine-imported scene (works in exported builds, where the
	# raw glTF is remapped away); fall back to runtime glTF parsing for
	# external --geometry directories and headless runs without an import.
	if ResourceLoader.exists(path, "PackedScene"):
		var ps: PackedScene = load(path)
		if ps != null:
			scene = ps.instantiate()
	if scene == null:
		var doc := GLTFDocument.new()
		var state := GLTFState.new()
		var err := doc.append_from_file(path, state)
		if err != OK:
			push_warning("DetectorLoader: failed to read '%s' (error %d)" % [path, err])
			return null
		scene = doc.generate_scene(state)
	if scene == null:
		push_warning("DetectorLoader: '%s' produced no scene" % path)
		return null
	scene.name = det_name
	var root := Node3D.new()
	root.name = det_name
	root.scale = Vector3.ONE * MM_TO_M
	root.add_child(scene)
	var mat := _material_for(det_name)
	_apply_material_recursive(root, mat)
	return root


func _material_for(det_name: String) -> ShaderMaterial:
	var stem := det_name.to_lower()
	var chosen := []
	for entry in DETECTOR_MATERIALS:
		var matched := false
		for kw in entry[0]:
			if stem.contains(kw):
				matched = true
				break
		if matched:
			chosen = [entry[1], entry[2], entry[3]]
			break
	if chosen.is_empty():
		var fb: Array = FALLBACK_PALETTE[_fallback_idx % FALLBACK_PALETTE.size()]
		_fallback_idx += 1
		chosen = fb
	var mat := ShaderMaterial.new()
	mat.shader = load(DETECTOR_SHADER)
	mat.set_shader_parameter("albedo", chosen[0])
	mat.set_shader_parameter("metallic", chosen[1])
	mat.set_shader_parameter("roughness", chosen[2])
	return mat


func _apply_material_recursive(node: Node, mat: Material) -> void:
	var mi := node as MeshInstance3D
	if mi != null:
		mi.material_override = mat
		mi.gi_mode = GeometryInstance3D.GI_MODE_STATIC
	for child in node.get_children():
		_apply_material_recursive(child, mat)
