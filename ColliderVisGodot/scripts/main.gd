extends Node3D
## ColliderVis (Godot 4) — entry point.
##
## Everything is built procedurally at startup: the experimental-hall room,
## the cinematic light rig, the high-quality environment (SDFGI global
## illumination, volumetric god-rays, glow, AgX tonemap), the detector
## geometry (loaded from glTF at runtime), the collision-event display, the
## in-game UI, and the camera/post-FX stack (DOF bokeh, lens flares, motion
## blur, chromatic aberration, vignette, grain).
##
## The user should not need to touch anything in the editor.
##
## Command-line options (after `--`):
##   --geometry=<dir>     directory of sub-detector .gltf files
##                        (default: res://assets/detector)
##   --events=<dir|file>  directory of event_NNNN.json files, a single .json,
##                        or an EDM4HEP .root file (needs python3 + uproot)
##   --screenshot=<path>  render N frames headlessly, save a PNG, then quit
##   --frames=<N>         frames to render before the screenshot (default 150,
##                        gives SDFGI/TAA time to converge)
##   --hud                keep the UI overlay visible in the screenshot
##   --hide=<groups>      comma-separated sub-detector groups to start hidden
##   --no-event           don't auto-load the first event
##   --mode=<orbit|fly|walk>  starting camera mode (default orbit)

const DetectorLoader := preload("res://scripts/detector_loader.gd")
const EventDisplay := preload("res://scripts/event_display.gd")
const OrbitCamera := preload("res://scripts/orbit_camera.gd")
const Character := preload("res://scripts/character.gd")
const UI := preload("res://scripts/ui.gd")

const DEFAULT_GEOMETRY_DIR := "res://assets/detector"
const DEFAULT_EVENTS_DIR := "res://events"

## Experimental hall dimensions (metres). The detector (~9 m across) sits at
## the origin; the hall is sized like a real underground cavern around it.
const HALL_HALF_X := 13.5
const HALL_HALF_Z := 17.0
const HALL_FLOOR_Y := -6.5
const HALL_CEIL_Y := 9.5

enum CamMode { ORBIT, FLY, WALK }

var detector_groups: Dictionary = {}   # group name -> Array[Node3D]
var group_order: Array = []            # stable hotkey ordering
var event_display: Node3D = null
var event_files: Array = []
var event_index := -1
var ip_light: OmniLight3D = null
var orbit_camera: Camera3D = null
var character: CharacterBody3D = null
var ui: CanvasLayer = null
var post_fx_mat: ShaderMaterial = null
var environment: Environment = null
var voxel_gi: VoxelGI = null
var cam_mode: CamMode = CamMode.ORBIT
var cutaway_enabled := true
var phi_min := 0.0
var phi_max := 90.0

var _args := {}
var _prev_cam_xform := Transform3D.IDENTITY


func _ready() -> void:
	_args = _parse_user_args()
	_setup_shader_globals()
	_build_environment()
	_build_hall()
	_build_light_rig()
	_load_geometry(String(_args.get("geometry", DEFAULT_GEOMETRY_DIR)))
	_setup_baked_gi()
	for g in String(_args.get("hide", "")).split(",", false):
		if detector_groups.has(g):
			for node in detector_groups[g]:
				(node as Node3D).visible = false
	open_event_path(String(_args.get("events", DEFAULT_EVENTS_DIR)))
	if not event_files.is_empty() and not _args.has("no-event"):
		_show_event(0)
	_spawn_cameras()
	match String(_args.get("mode", "orbit")):
		"fly":
			cycle_camera_mode()
		"walk":
			cycle_camera_mode()
			cycle_camera_mode()
	_build_post_fx()
	ui = UI.new()
	ui.name = "UI"
	add_child(ui)
	ui.build(self)
	if _args.has("screenshot") and not _args.has("hud"):
		ui.visible = false
	if _args.has("screenshot"):
		_run_screenshot_mode()


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

func _parse_user_args() -> Dictionary:
	var out := {}
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--"):
			var body := arg.substr(2)
			var eq := body.find("=")
			if eq >= 0:
				out[body.substr(0, eq)] = body.substr(eq + 1)
			else:
				out[body] = "true"
	return out


# ──────────────────────────────────────────────────────────────────────────────
# Environment — the "super high quality lighting" core
# ──────────────────────────────────────────────────────────────────────────────

func _setup_shader_globals() -> void:
	# Phi-cutaway parameters shared by every detector material.
	for params in [["cv_phi_min", phi_min], ["cv_phi_max", phi_max],
			["cv_cutaway_enabled", 1.0 if cutaway_enabled else 0.0]]:
		RenderingServer.global_shader_parameter_add(
			params[0], RenderingServer.GLOBAL_VAR_TYPE_FLOAT, params[1])


func _build_environment() -> void:
	var env := Environment.new()

	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.004, 0.005, 0.008)

	# Low cool ambient floor — SDFGI provides the real bounce light.
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.70, 0.82, 0.90)
	env.ambient_light_energy = 0.18

	# Real-time global illumination: light bounces off the hall and the
	# detector's metal surfaces; emissive tracks tint their surroundings.
	env.sdfgi_enabled = true
	env.sdfgi_use_occlusion = true
	env.sdfgi_bounce_feedback = 0.6
	env.sdfgi_cascades = 4
	env.sdfgi_min_cell_size = 0.12
	env.sdfgi_energy = 1.1

	# Contact shadows in detector crevices + small-scale indirect light.
	env.ssao_enabled = true
	env.ssao_radius = 1.5
	env.ssao_intensity = 2.0
	env.ssao_power = 1.8
	env.ssil_enabled = true
	env.ssil_radius = 3.0
	env.ssil_intensity = 1.0

	# Screen-space reflections on the polished metal.
	env.ssr_enabled = true
	env.ssr_max_steps = 96
	env.ssr_fade_in = 0.15
	env.ssr_fade_out = 2.0
	env.ssr_depth_tolerance = 0.4

	# Bloom — the emissive particle tracks should glow hard.
	env.glow_enabled = true
	env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SCREEN
	env.glow_intensity = 0.9
	env.glow_strength = 1.0
	env.glow_bloom = 0.02
	env.glow_hdr_threshold = 1.35
	env.set_glow_level(1, 0.6)
	env.set_glow_level(2, 0.9)
	env.set_glow_level(3, 1.0)
	env.set_glow_level(4, 0.7)
	env.set_glow_level(5, 0.5)

	# Indoor laboratory haze: subtle — just enough for the practical lights
	# to draw visible volumetric shafts without milking out the scene.
	env.volumetric_fog_enabled = true
	env.volumetric_fog_density = 0.0028
	env.volumetric_fog_albedo = Color(0.5, 0.6, 0.7)
	env.volumetric_fog_emission = Color(0.0, 0.0, 0.0)
	env.volumetric_fog_anisotropy = 0.55
	env.volumetric_fog_length = 48.0
	env.volumetric_fog_gi_inject = 0.25
	env.volumetric_fog_ambient_inject = 0.0

	# Filmic response with graceful highlight rolloff for the HDR emissives.
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.tonemap_exposure = 1.15

	# Global grade: deeper blacks, light desaturation toward the teal void.
	env.adjustment_enabled = true
	env.adjustment_contrast = 1.08
	env.adjustment_saturation = 1.02
	env.adjustment_brightness = 1.0

	var we := WorldEnvironment.new()
	we.name = "WorldEnvironment"
	we.environment = env
	add_child(we)
	environment = env


## Bake high-quality GI for the (static) detector + hall. VoxelGI gives
## markedly better indirect light and rough reflections than SDFGI for a
## bounded scene like ours; the voxel field is baked once at startup (and
## re-baked when new geometry is loaded), which is fine because the
## detector doesn't move. `--gi=sdfgi` skips the bake and keeps SDFGI;
## if the bake fails for any reason SDFGI stays on as the fallback.
func _setup_baked_gi() -> void:
	if String(_args.get("gi", "voxel")) != "voxel":
		return
	voxel_gi = VoxelGI.new()
	voxel_gi.name = "VoxelGI"
	# Cover the hall with some headroom; subdiv 256 -> ~16 cm voxels.
	voxel_gi.size = Vector3(HALL_HALF_X * 2.0 + 2.0,
		HALL_CEIL_Y - HALL_FLOOR_Y + 2.0, HALL_HALF_Z * 2.0 + 2.0)
	voxel_gi.position = Vector3(0, (HALL_FLOOR_Y + HALL_CEIL_Y) / 2.0, 0)
	voxel_gi.subdiv = VoxelGI.SUBDIV_256
	add_child(voxel_gi)
	_rebake_gi()

	# Sharp specular reflections on the polished metal, refreshed once.
	var probe := ReflectionProbe.new()
	probe.name = "HallReflectionProbe"
	probe.update_mode = ReflectionProbe.UPDATE_ONCE
	probe.size = voxel_gi.size
	probe.position = voxel_gi.position
	probe.box_projection = true
	probe.intensity = 0.8
	add_child(probe)


func _rebake_gi() -> void:
	if voxel_gi == null:
		return
	var t0 := Time.get_ticks_msec()
	voxel_gi.bake(self)
	if voxel_gi.data != null:
		environment.sdfgi_enabled = false
		print("ColliderVis: VoxelGI baked in %.1f s" % ((Time.get_ticks_msec() - t0) / 1000.0))
	else:
		environment.sdfgi_enabled = true
		push_warning("ColliderVis: VoxelGI bake produced no data; keeping SDFGI")


# ──────────────────────────────────────────────────────────────────────────────
# Experimental hall — dark sci-fi cavern enclosing the detector
# ──────────────────────────────────────────────────────────────────────────────

func _hall_material(tint: Color, metallic: float, roughness: float) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = tint
	m.metallic = metallic
	m.roughness = roughness
	return m


func _spawn_slab(slab_name: String, pos: Vector3, size: Vector3,
		mat: Material, with_collision := false) -> MeshInstance3D:
	var box := BoxMesh.new()
	box.size = size
	var mi := MeshInstance3D.new()
	mi.name = slab_name
	mi.mesh = box
	mi.material_override = mat
	mi.position = pos
	mi.gi_mode = GeometryInstance3D.GI_MODE_STATIC
	add_child(mi)
	if with_collision:
		var body := StaticBody3D.new()
		var shape := CollisionShape3D.new()
		var bs := BoxShape3D.new()
		bs.size = size
		shape.shape = bs
		body.add_child(shape)
		mi.add_child(body)
	return mi


func _build_hall() -> void:
	var w := HALL_HALF_X * 2.0
	var d := HALL_HALF_Z * 2.0
	var h := HALL_CEIL_Y - HALL_FLOOR_Y
	var t := 0.4   # slab thickness

	# Floor — gunmetal, smooth-but-not-mirror (catches reflections).
	var floor_mat := _hall_material(Color(0.05, 0.06, 0.07), 0.6, 0.32)
	_spawn_slab("Hall_Floor", Vector3(0, HALL_FLOOR_Y - t / 2.0, 0), Vector3(w, t, d), floor_mat, true)

	# Ceiling — darker, matte.
	var ceil_mat := _hall_material(Color(0.02, 0.025, 0.035), 0.3, 0.7)
	_spawn_slab("Hall_Ceiling", Vector3(0, HALL_CEIL_Y + t / 2.0, 0), Vector3(w, t, d), ceil_mat)

	# Walls — slightly bluer than the floor, brushed feel.
	var wall_mat := _hall_material(Color(0.045, 0.055, 0.075), 0.4, 0.55)
	var ymid := (HALL_FLOOR_Y + HALL_CEIL_Y) / 2.0
	_spawn_slab("Hall_Wall_PosX", Vector3(HALL_HALF_X + t / 2.0, ymid, 0), Vector3(t, h, d), wall_mat, true)
	_spawn_slab("Hall_Wall_NegX", Vector3(-HALL_HALF_X - t / 2.0, ymid, 0), Vector3(t, h, d), wall_mat, true)
	_spawn_slab("Hall_Wall_PosZ", Vector3(0, ymid, HALL_HALF_Z + t / 2.0), Vector3(w, h, t), wall_mat, true)
	_spawn_slab("Hall_Wall_NegZ", Vector3(0, ymid, -HALL_HALF_Z - t / 2.0), Vector3(w, h, t), wall_mat, true)


# ──────────────────────────────────────────────────────────────────────────────
# Light rig — warm key panel, cool cyan wall strips, rim accent
# (ported from AColliderVisGameMode::SetupAtmosphere)
# ──────────────────────────────────────────────────────────────────────────────

func _add_fixture_panel(pos: Vector3, size: Vector3, color: Color,
		energy: float) -> void:
	# Visible emissive housing for each practical light.
	var box := BoxMesh.new()
	box.size = size
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(0.05, 0.05, 0.05)
	m.metallic = 0.2
	m.roughness = 0.6
	m.emission_enabled = true
	m.emission = color
	m.emission_energy_multiplier = energy
	var mi := MeshInstance3D.new()
	mi.mesh = box
	mi.material_override = m
	mi.position = pos
	mi.gi_mode = GeometryInstance3D.GI_MODE_STATIC
	add_child(mi)


func _add_spot(pos: Vector3, color: Color, energy: float, angle_deg: float,
		range_m: float, size: float, fog_energy: float) -> SpotLight3D:
	var l := SpotLight3D.new()
	l.position = pos
	l.light_color = color
	l.light_energy = energy
	l.spot_angle = angle_deg
	l.spot_range = range_m
	l.light_size = size
	l.shadow_enabled = true
	l.shadow_blur = 1.5
	l.light_volumetric_fog_energy = fog_energy
	l.light_specular = 0.8
	add_child(l)
	l.look_at_from_position(pos, Vector3.ZERO, Vector3.UP if absf(pos.normalized().y) < 0.95 else Vector3.FORWARD)
	return l


func _build_light_rig() -> void:
	const KEY_WARM := Color(1.0, 0.83, 0.64)    # ~4400 K clean-room panel
	const COOL_CYAN := Color(0.70, 0.90, 1.0)   # ~7000 K wall strips
	const RIM_COOL := Color(0.92, 0.96, 1.0)    # ~6500 K rim accent

	# Key — big warm ceiling panel, offset so the detector gets shape from it.
	var key_pos := Vector3(-5.0, HALL_CEIL_Y - 0.2, 2.0)
	_add_spot(key_pos, KEY_WARM, 110.0, 110.0, 35.0, 1.2, 0.5)
	_add_fixture_panel(Vector3(key_pos.x, HALL_CEIL_Y - 0.05, key_pos.z),
		Vector3(5.0, 0.1, 3.0), KEY_WARM, 2.0)

	# Cool cyan strips on both side walls (long, narrow, low energy).
	for sx in [-1.0, 1.0]:
		var p := Vector3(sx * (HALL_HALF_X - 0.3), 2.5, 0.0)
		_add_spot(p, COOL_CYAN, 55.0, 120.0, 30.0, 1.0, 0.3)
		_add_fixture_panel(Vector3(sx * (HALL_HALF_X - 0.06), 2.5, 0.0),
			Vector3(0.1, 0.5, 12.0), COOL_CYAN, 1.6)

	# Neutral work lights on the ±Z end walls so the barrel face the camera
	# sees never falls to black (the cavern equivalent of bounce cards).
	for sz in [-1.0, 1.0]:
		var p := Vector3(2.0, 4.0, sz * (HALL_HALF_Z - 0.5))
		_add_spot(p, Color(0.95, 0.97, 1.0), 28.0, 100.0, 34.0, 0.9, 0.2)

	# Rim accent from behind/above — separates the detector from the far wall.
	var rim_pos := Vector3(-8.0, 6.5, -(HALL_HALF_Z - 1.0))
	_add_spot(rim_pos, RIM_COOL, 40.0, 90.0, 38.0, 0.8, 0.25)
	_add_fixture_panel(Vector3(-8.0, 6.5, -(HALL_HALF_Z - 0.15)),
		Vector3(2.0, 6.0, 0.1), RIM_COOL, 1.2)

	# Faint under-glow so the bottom of the barrel doesn't go to pure black.
	var under := OmniLight3D.new()
	under.position = Vector3(0, HALL_FLOOR_Y + 0.5, 0)
	under.light_color = Color(0.45, 0.62, 0.85)
	under.light_energy = 4.0
	under.omni_range = 14.0
	under.shadow_enabled = false
	under.light_volumetric_fog_energy = 0.15
	add_child(under)

	# Interaction-point light — turned on when an event is displayed so the
	# glowing tracks visibly illuminate the detector interior.
	ip_light = OmniLight3D.new()
	ip_light.position = Vector3.ZERO
	ip_light.light_color = Color(1.0, 0.72, 0.42)
	ip_light.light_energy = 0.0
	ip_light.omni_range = 11.0
	ip_light.shadow_enabled = true
	ip_light.light_volumetric_fog_energy = 0.8
	add_child(ip_light)


# ──────────────────────────────────────────────────────────────────────────────
# Geometry
# ──────────────────────────────────────────────────────────────────────────────

func _load_geometry(dir: String) -> void:
	var loader := DetectorLoader.new()
	var loaded: Dictionary = loader.load_directory(dir)
	if loaded.is_empty():
		push_warning("ColliderVis: no .gltf geometry found in '%s'" % dir)
		return
	_register_geometry(loaded)


func _register_geometry(loaded: Dictionary) -> void:
	for det_name in loaded:
		var node: Node3D = loaded[det_name]
		add_child(node)
		var group := _group_for(det_name)
		if not detector_groups.has(group):
			detector_groups[group] = []
			group_order.append(group)
		detector_groups[group].append(node)
	group_order.sort()
	print("ColliderVis: loaded %d sub-detectors in %d groups: %s"
		% [loaded.size(), group_order.size(), ", ".join(group_order)])


func _group_for(det_name: String) -> String:
	# NozzleBCH_left / NozzleBCH_right -> NozzleBCH, etc.
	for suffix in ["_left", "_right", "_Left", "_Right"]:
		if det_name.ends_with(suffix):
			return det_name.substr(0, det_name.length() - suffix.length())
	return det_name


## Swap in a different detector at runtime from a directory of per-sub-
## detector glTF files (the output of `./run.sh split-convert`), then
## re-bake the GI around the new geometry.
func load_detector_dir(dir: String) -> void:
	var loader := DetectorLoader.new()
	var loaded: Dictionary = loader.load_directory(dir)
	if loaded.is_empty():
		_error("No .gltf/.glb sub-detector files found in:\n%s" % dir)
		return
	for g in detector_groups:
		for node in detector_groups[g]:
			(node as Node3D).queue_free()
	detector_groups.clear()
	group_order.clear()
	_register_geometry(loaded)
	# Let the freed geometry actually leave the tree before re-voxelizing.
	await get_tree().process_frame
	_rebake_gi()
	if ui != null:
		ui.reset_detector_list()


func set_group_visible(group: String, vis: bool) -> void:
	for node in detector_groups.get(group, []):
		(node as Node3D).visible = vis
	_ui_refresh()


func set_all_groups(vis: bool) -> void:
	for g in group_order:
		for node in detector_groups[g]:
			(node as Node3D).visible = vis
	_ui_refresh()


func set_cutaway(on: bool) -> void:
	cutaway_enabled = on
	RenderingServer.global_shader_parameter_set(
		"cv_cutaway_enabled", 1.0 if cutaway_enabled else 0.0)
	_ui_refresh()


func set_phi_max(value: float) -> void:
	phi_max = clampf(value, phi_min, 360.0)
	RenderingServer.global_shader_parameter_set("cv_phi_max", phi_max)


# ──────────────────────────────────────────────────────────────────────────────
# Events — JSON directories, single files, EDM4HEP ROOT conversion
# ──────────────────────────────────────────────────────────────────────────────

## Entry point for everything the user can hand us: a directory of event
## JSONs, one .json file, or an EDM4HEP/key4hep .root file.
func open_event_path(path: String) -> void:
	if path.is_empty():
		return
	if path.get_extension().to_lower() == "root":
		_convert_and_load_root(path)
		return
	if path.get_extension().to_lower() == "json":
		# Load the file's whole directory so Space/N cycles its siblings.
		var dir := path.get_base_dir()
		_load_events_from_dir(dir)
		var idx := event_files.find(path)
		if idx >= 0 and not _args.has("no-event"):
			_show_event(idx)
		return
	_load_events_from_dir(path)


func _load_events_from_dir(dir: String) -> void:
	var found := []
	var da := DirAccess.open(dir)
	if da != null:
		for f in da.get_files():
			if f.get_extension() == "json":
				found.append(dir.path_join(f))
		found.sort()
	if found.is_empty():
		push_warning("ColliderVis: no event .json files in '%s'" % dir)
		return
	event_files = found
	event_index = -1
	print("ColliderVis: found %d event file(s) in %s" % [event_files.size(), dir])


func _convert_and_load_root(root_path: String) -> void:
	var script := _find_converter()
	if script.is_empty():
		_error("EDM4HEP conversion needs ColliderVis/Tools/edm4hep_to_json.py.\n"
			+ "Set the COLLIDERVIS_CONVERTER environment variable to its path,\n"
			+ "or convert manually:\n  python3 edm4hep_to_json.py <file.root> <outdir>")
		return
	var out_dir := OS.get_user_data_dir().path_join(
		"converted/" + root_path.get_file().get_basename())
	DirAccess.make_dir_recursive_absolute(out_dir)
	print("ColliderVis: converting %s -> %s" % [root_path, out_dir])
	var output := []
	var code := OS.execute("python3", [script, root_path, out_dir], output, true)
	if code != 0:
		_error("EDM4HEP conversion failed (exit %d).\n%s\n\n"
			% [code, "\n".join(output).right(600)]
			+ "python3 with `uproot` and `awkward` installed is required:\n"
			+ "  pip install uproot awkward")
		return
	_load_events_from_dir(out_dir)
	if not event_files.is_empty():
		_show_event(0)


func _find_converter() -> String:
	var candidates := [
		OS.get_environment("COLLIDERVIS_CONVERTER"),
		ProjectSettings.globalize_path("res://").path_join("../ColliderVis/Tools/edm4hep_to_json.py"),
		OS.get_executable_path().get_base_dir().path_join("edm4hep_to_json.py"),
		OS.get_executable_path().get_base_dir().path_join("Tools/edm4hep_to_json.py"),
	]
	for c in candidates:
		if not String(c).is_empty() and FileAccess.file_exists(c):
			return c
	return ""


func show_event_index(idx: int) -> void:
	if not event_files.is_empty() and idx != event_index:
		_show_event(idx)


func show_relative_event(step: int) -> void:
	if not event_files.is_empty():
		_show_event(event_index + step)


func _show_event(idx: int) -> void:
	if event_files.is_empty():
		return
	event_index = wrapi(idx, 0, event_files.size())
	if event_display != null:
		event_display.queue_free()
	event_display = EventDisplay.new()
	add_child(event_display)
	event_display.load_event(event_files[event_index])
	ip_light.light_energy = 2.0
	_ui_refresh()


func event_summary_bbcode() -> String:
	if event_display == null:
		return "[i]No event loaded.\nOpen a .json or EDM4HEP .root file above.[/i]"
	var ed: Node3D = event_display
	var s := "[b]Event %d[/b]  (run %d)\n" % [ed.event_number, ed.run_number]
	s += "Reco tracks: %d   Calo hits: %d  (ΣE = %.1f GeV)   Truth lines: %d\n" \
		% [ed.track_infos.size(), ed.n_calo_hits, ed.calo_energy_sum, ed.mc_infos.size()]

	var tracks: Array = ed.track_infos.duplicate()
	tracks.sort_custom(func(a, b): return a.p > b.p)
	s += "\n[b]Reco tracks[/b] [color=#778]by momentum[/color]\n[code]"
	for i in mini(tracks.size(), 14):
		var t: Dictionary = tracks[i]
		var sign := "+" if t.charge > 0 else ("-" if t.charge < 0 else "0")
		s += "%-6s q=%s  p=%6.1f GeV\n" % [EventDisplay.pdg_name(t.pdg), sign, t.p]
	if tracks.size() > 14:
		s += "… %d more\n" % (tracks.size() - 14)
	s += "[/code]"

	if not ed.mc_infos.is_empty():
		var mc: Array = ed.mc_infos.duplicate()
		mc.sort_custom(func(a, b): return a.p > b.p)
		s += "\n[b]Truth particles[/b]\n[code]"
		for i in mini(mc.size(), 10):
			var m: Dictionary = mc[i]
			s += "%-6s p=%6.1f GeV  status=%d\n" % [EventDisplay.pdg_name(m.pdg), m.p, m.status]
		if mc.size() > 10:
			s += "… %d more\n" % (mc.size() - 10)
		s += "[/code]"
	return s


# ──────────────────────────────────────────────────────────────────────────────
# Cameras & post FX
# ──────────────────────────────────────────────────────────────────────────────

func _spawn_cameras() -> void:
	orbit_camera = OrbitCamera.new()
	orbit_camera.name = "OrbitCamera"
	add_child(orbit_camera)
	orbit_camera.current = true
	_prev_cam_xform = orbit_camera.global_transform


func current_camera() -> Camera3D:
	if cam_mode == CamMode.WALK and character != null:
		return character.camera
	return orbit_camera


func camera_mode_name() -> String:
	match cam_mode:
		CamMode.ORBIT: return "Orbit camera"
		CamMode.FLY: return "Fly camera"
		CamMode.WALK: return "Third person"
	return ""


func cycle_camera_mode() -> void:
	match cam_mode:
		CamMode.ORBIT:
			cam_mode = CamMode.FLY
			orbit_camera.set_fly(true)
		CamMode.FLY:
			cam_mode = CamMode.WALK
			orbit_camera.set_fly(false)
			if character == null:
				character = Character.new()
				character.name = "Explorer"
				character.position = Vector3(9.5, HALL_FLOOR_Y + 1.2, 4.0)
				add_child(character)
			character.visible = true
			character.camera.current = true
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		CamMode.WALK:
			cam_mode = CamMode.ORBIT
			if character != null:
				character.visible = false
			orbit_camera.current = true
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	_ui_refresh()


func _build_post_fx() -> void:
	# Full-screen lens pass: motion blur, lens flares, CA, vignette, grain.
	var layer := CanvasLayer.new()
	layer.name = "PostFX"
	layer.layer = 10
	var rect := ColorRect.new()
	rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	post_fx_mat = ShaderMaterial.new()
	post_fx_mat.shader = load("res://shaders/post_fx.gdshader")
	rect.material = post_fx_mat
	layer.add_child(rect)
	add_child(layer)


func _process(_delta: float) -> void:
	# Feed the camera's screen-space motion to the motion-blur pass.
	var cam := current_camera()
	if cam == null or post_fx_mat == null:
		return
	var xf := cam.global_transform
	var f0 := -_prev_cam_xform.basis.z
	var f1 := -xf.basis.z
	var dx := f1.dot(_prev_cam_xform.basis.x)
	var dy := f1.dot(_prev_cam_xform.basis.y)
	# Lateral translation also contributes (parallax blur).
	var dpos := (xf.origin - _prev_cam_xform.origin)
	dx += dpos.dot(_prev_cam_xform.basis.x) * 0.01
	dy += dpos.dot(_prev_cam_xform.basis.y) * 0.01
	var motion := Vector2(dx, -dy) * 0.55
	post_fx_mat.set_shader_parameter("motion_vec", motion)
	_prev_cam_xform = xf


# ──────────────────────────────────────────────────────────────────────────────
# Input
# ──────────────────────────────────────────────────────────────────────────────

func _ui_refresh() -> void:
	if ui != null:
		ui.refresh()


func _unhandled_key_input(event: InputEvent) -> void:
	var k := event as InputEventKey
	if k == null or not k.pressed or k.echo:
		return
	match k.keycode:
		KEY_ESCAPE:
			if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
				Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
				if cam_mode == CamMode.FLY:
					cam_mode = CamMode.ORBIT
					orbit_camera.set_fly(false)
					_ui_refresh()
			else:
				ui.toggle_menu()
		KEY_TAB:
			cycle_camera_mode()
		KEY_SPACE:
			# In third-person mode Space is the jump key (handled by the
			# character while the mouse is captured); otherwise: next event.
			if not (cam_mode == CamMode.WALK
					and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED):
				show_relative_event(1)
		KEY_N:
			show_relative_event(1)
		KEY_B:
			show_relative_event(-1)
		KEY_C:
			set_cutaway(not cutaway_enabled)
		KEY_BRACKETLEFT:
			set_phi_max(phi_max - 15.0)
			_ui_refresh()
		KEY_BRACKETRIGHT:
			set_phi_max(phi_max + 15.0)
			_ui_refresh()
		KEY_H:
			ui.visible = not ui.visible
		KEY_0:
			set_all_groups(true)
		_:
			if k.keycode >= KEY_1 and k.keycode <= KEY_9:
				var idx := k.keycode - KEY_1
				if idx < group_order.size():
					var g: String = group_order[idx]
					var on: bool = (detector_groups[g][0] as Node3D).visible
					set_group_visible(g, not on)


# ──────────────────────────────────────────────────────────────────────────────
# Headless still-render mode
# ──────────────────────────────────────────────────────────────────────────────

func _run_screenshot_mode() -> void:
	var path := String(_args["screenshot"])
	var frames := int(String(_args.get("frames", "150")))
	print("ColliderVis: rendering %d frames, then saving %s" % [frames, path])
	for i in frames:
		await get_tree().process_frame
	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(path)
	if err == OK:
		print("ColliderVis: screenshot saved to ", path)
	else:
		printerr("ColliderVis: FAILED to save screenshot (error %d)" % err)
	get_tree().quit(0 if err == OK else 1)


func _error(msg: String) -> void:
	printerr("ColliderVis: ", msg.replace("\n", " "))
	if ui != null:
		ui.show_error(msg)
