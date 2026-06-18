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

## Studio rig positions (metres). The detector (~9 m across) floats at the
## origin inside a softly lit dome; an "infinite" glass floor sits at the
## beam plane (y = 0) so you can walk right up to the interaction point.
const RIG_HALF_X := 13.5
const RIG_HALF_Z := 17.0
const RIG_CEIL_Y := 9.5
const DOME_RADIUS := 70.0

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
var glass_floor: MeshInstance3D = null
var dome: MeshInstance3D = null
var passthrough_on := false
var _bg_color := Color(0.008, 0.011, 0.018)
var rig_lights: Array = []          # [[Light3D, base_energy], ...]
var _shadow_casters: Array = []     # lights that cast real-time shadows
var light_scale := 0.85             # settings: global rig brightness
var show_events := true             # settings: event display on/off
var cam_mode: CamMode = CamMode.ORBIT
var cutaway_enabled := true
var phi_min := 0.0
var phi_max := 90.0

var _args := {}
var _prev_cam_xform := Transform3D.IDENTITY

## Phones/tablets and Quest: no keyboard/mouse, tight GPU budget.
var is_mobile := OS.has_feature("mobile")
var xr_origin: XROrigin3D = null
var xr_camera: XRCamera3D = null
var xr_left: XRController3D = null
var xr_right: XRController3D = null
var xr_ray: RayCast3D = null
var xr_dot: MeshInstance3D = null
var vr_menu: Node3D = null
var _xr_trigger_down := false


func _ready() -> void:
	_args = _parse_user_args()
	_setup_shader_globals()
	_build_environment()
	_build_stage()
	_build_light_rig()
	_load_geometry(String(_args.get("geometry", _default_geometry_dir())))
	_setup_baked_gi()
	for g in String(_args.get("hide", "")).split(",", false):
		if detector_groups.has(g):
			for node in detector_groups[g]:
				(node as Node3D).visible = false
	open_event_path(String(_args.get("events", DEFAULT_EVENTS_DIR)))
	if not event_files.is_empty() and not _args.has("no-event"):
		_show_event(0)
	_spawn_cameras()
	# Default render scale: low-ish on desktop (FSR2 hides it well);
	# floor it on mobile where smoothness beats resolution.
	set_render_scale(0.5 if is_mobile else 0.6)
	_build_post_fx()
	# Initialize XR FIRST — head tracking (xr_camera.current = true) must be
	# established before any of the mobile-optimization code below runs. If
	# that code ever errors, the headset must NOT be left rendering from the
	# static desktop camera (which looks exactly like broken head tracking).
	var xr_ok := false
	if not _args.has("screenshot"):
		xr_ok = _try_init_xr()
	if is_mobile:
		apply_quality("performance")
		_optimize_geometry_for_mobile()
	if not xr_ok:
		match String(_args.get("mode", "orbit")):
			"fly":
				cycle_camera_mode()
			"walk":
				cycle_camera_mode()
				cycle_camera_mode()
	ui = UI.new()
	ui.name = "UI"
	add_child(ui)
	ui.build(self)
	if _args.has("screenshot") and not _args.has("hud"):
		ui.visible = false
	if _args.has("screenshot"):
		_run_screenshot_mode()
	elif xr_ok:
		pass   # VR session running; flat-screen input stays available too
	else:
		_sync_mouse_mode()   # menu starts closed -> mouse drives the camera


# ──────────────────────────────────────────────────────────────────────────────
# VR (Meta Quest via OpenXR — enabled only in Android builds)
# ──────────────────────────────────────────────────────────────────────────────

func _try_init_xr() -> bool:
	var xr := XRServer.find_interface("OpenXR")
	if xr == null:
		return false
	if not xr.is_initialized() and not xr.initialize():
		return false
	var vp := get_viewport()
	vp.use_xr = true
	# Foveated rendering. CRITICAL: on the Forward Mobile renderer the
	# `xr/openxr/foveation_level` project setting does NOTHING — foveation is
	# driven by Variable Rate Shading. Without this the whole frame renders at
	# full rate edge-to-edge (a big, previously-missed GPU cost on the Quest).
	vp.vrs_mode = Viewport.VRS_XR
	# OpenXR runs its own frame pacing; Godot's vsync fights it and adds
	# latency/judder. Hand timing to the runtime.
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	# Match physics to the headset refresh so tracked motion stays smooth.
	Engine.physics_ticks_per_second = 72
	# Headset perf: low render scale + a little MSAA (cheap on the tiler since
	# it resolves in tile memory). The render scale absorbs the fragment cost
	# of the cull_disabled detector overdraw; VRS above drops peripheral cost.
	vp.scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
	vp.scaling_3d_scale = 0.5
	vp.msaa_3d = Viewport.MSAA_2X
	# Stand on the glass at the beam plane, a few metres from the barrel.
	xr_origin = XROrigin3D.new()
	xr_origin.name = "XROrigin"
	xr_origin.position = Vector3(9.0, 0.0, 5.0)
	add_child(xr_origin)
	xr_camera = XRCamera3D.new()
	xr_origin.add_child(xr_camera)
	# CRITICAL: the XR camera must be the current camera, otherwise the
	# viewport keeps rendering from the static desktop camera and the HMD
	# pose only shifts that fixed image — i.e. the scene appears head-locked.
	xr_camera.current = true
	for hand in ["left_hand", "right_hand"]:
		var ctl := XRController3D.new()
		ctl.tracker = hand
		xr_origin.add_child(ctl)
		ctl.button_pressed.connect(_on_xr_button.bind(hand))
		if hand == "left_hand":
			xr_left = ctl
		else:
			xr_right = ctl

	# Right-hand laser pointer for the in-VR menu.
	xr_ray = RayCast3D.new()
	xr_ray.target_position = Vector3(0, 0, -6)
	xr_ray.collide_with_areas = false
	xr_ray.collision_mask = 1 << 4   # only the VR menu panel
	xr_right.add_child(xr_ray)
	var beam := MeshInstance3D.new()
	var bm := CylinderMesh.new()
	bm.top_radius = 0.004
	bm.bottom_radius = 0.004
	bm.height = 6.0
	beam.mesh = bm
	beam.rotation_degrees = Vector3(-90, 0, 0)   # cylinder runs along -Z
	beam.position = Vector3(0, 0, -3.0)
	var beam_mat := StandardMaterial3D.new()
	beam_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	beam_mat.albedo_color = Color(0.3, 0.8, 1.0, 0.5)
	beam_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	beam.material_override = beam_mat
	beam.gi_mode = GeometryInstance3D.GI_MODE_DISABLED
	xr_ray.add_child(beam)
	xr_dot = MeshInstance3D.new()
	var dm := SphereMesh.new()
	dm.radius = 0.02
	dm.height = 0.04
	xr_dot.mesh = dm
	var dot_mat := StandardMaterial3D.new()
	dot_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	dot_mat.albedo_color = Color(0.5, 0.9, 1.0)
	xr_dot.material_override = dot_mat
	xr_dot.gi_mode = GeometryInstance3D.GI_MODE_DISABLED
	xr_dot.visible = false
	add_child(xr_dot)

	# World-space VR menu (the 2D overlay can't render to a headset).
	vr_menu = preload("res://scripts/vr_menu.gd").new()
	add_child(vr_menu)
	vr_menu.setup(self)

	# Screen-space lens effects don't belong on a headset.
	var fx := get_node_or_null("PostFX")
	if fx != null:
		fx.visible = false
	if glass_floor != null:
		glass_floor.visible = true
	if _args.has("passthrough"):
		set_passthrough(true)
	print("ColliderVis: OpenXR session started")
	return true


## Reset the play area so the detector sits in front of you again.
func xr_recenter() -> void:
	var xr := XRServer.find_interface("OpenXR")
	if xr != null:
		XRServer.center_on_hmd(XRServer.RESET_BUT_KEEP_TILT, true)


## Mixed-reality passthrough: composite the headset cameras behind the scene
## by switching the OpenXR environment blend to alpha and clearing the
## background (the dome + glass floor hide so the detector floats in your
## real room). Uses core XRInterface blend modes — the Meta passthrough
## OpenXR extension (from the vendors plugin) backs ALPHA_BLEND on Quest.
func set_passthrough(on: bool) -> void:
	var xr := XRServer.find_interface("OpenXR")
	var vp := get_viewport()
	if on and xr != null:
		var modes: Array = xr.get_supported_environment_blend_modes()
		if not (XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND in modes):
			_error("Passthrough isn't available on this headset/runtime.")
			return
		xr.environment_blend_mode = XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND
		vp.transparent_bg = true
		environment.background_mode = Environment.BG_COLOR
		environment.background_color = Color(0, 0, 0, 0)
		if dome != null:
			dome.visible = false
		if glass_floor != null:
			glass_floor.visible = false
		passthrough_on = true
	else:
		if xr != null:
			xr.environment_blend_mode = XRInterface.XR_ENV_BLEND_MODE_OPAQUE
		vp.transparent_bg = false
		environment.background_mode = Environment.BG_COLOR
		environment.background_color = _bg_color
		if dome != null:
			dome.visible = true
		if glass_floor != null:
			glass_floor.visible = (cam_mode == CamMode.WALK) or xr_origin != null
		passthrough_on = false


## Quest controller map:
##   Y (left)        open / close the VR menu
##   right trigger   menu click when the menu is open, else next event
##   A (right)       next event        B (right)   previous event
##   X (left)        cutaway toggle
##   left trigger    previous event
##   either grip     cycle which sub-detector group is hidden (quick x-ray)
##   left stick      glide (head-relative)   right stick X   45° snap turn
var _xr_hide_idx := -1

func _on_xr_button(button_name: String, hand: String) -> void:
	# Y always toggles the menu, even while it's open.
	if button_name == "by_button" and hand == "left_hand":
		if vr_menu != null:
			vr_menu.toggle(_xr_head_xform())
		return
	# While the menu is open the trigger is the menu click (handled per-frame
	# in _process_xr); swallow the nav buttons so they don't also fire.
	if vr_menu != null and vr_menu.is_open():
		return
	match button_name:
		"trigger_click":
			show_relative_event(1 if hand == "right_hand" else -1)
		"ax_button":
			if hand == "right_hand":
				show_relative_event(1)        # A
			else:
				set_cutaway(not cutaway_enabled)   # X
		"by_button":
			show_relative_event(-1)           # B (right)
		"grip_click":
			# Step an "x-ray" cursor through the groups: each press un-hides
			# the previous group and hides the next one; wraps to all-on.
			if _xr_hide_idx >= 0 and _xr_hide_idx < group_order.size():
				set_group_visible(group_order[_xr_hide_idx], true)
			_xr_hide_idx += 1
			if _xr_hide_idx >= group_order.size():
				_xr_hide_idx = -1
			else:
				set_group_visible(group_order[_xr_hide_idx], false)


func _xr_head_xform() -> Transform3D:
	if xr_camera != null:
		return xr_camera.global_transform
	return Transform3D.IDENTITY


const XR_MOVE_SPEED := 2.5
const XR_SNAP_DEG := 45.0
var _xr_snap_ready := true

func _process_xr(delta: float) -> void:
	if xr_origin == null:
		return

	# Laser pointer + trigger-as-click while the VR menu is open.
	if vr_menu != null and vr_menu.is_open() and xr_ray != null:
		xr_ray.force_raycast_update()
		var hit: bool = xr_ray.is_colliding() and xr_ray.get_collider() == vr_menu.body
		var on_panel := false
		if hit:
			var p: Vector3 = xr_ray.get_collision_point()
			on_panel = vr_menu.point(p)
			xr_dot.global_position = p
		xr_dot.visible = on_panel
		var t_down: bool = xr_right != null and xr_right.is_button_pressed("trigger_click")
		if t_down != _xr_trigger_down:
			_xr_trigger_down = t_down
			vr_menu.click(t_down)
		# Don't also move/turn while pointing at the menu.
		return
	else:
		_xr_trigger_down = false
		if xr_dot != null:
			xr_dot.visible = false

	# Left stick: glide relative to where you're looking.
	if xr_left != null:
		var mv := xr_left.get_vector2("primary")
		if mv.length() > 0.12:
			var fwd := -xr_camera.global_transform.basis.z
			fwd.y = 0.0
			fwd = fwd.normalized()
			var right := xr_camera.global_transform.basis.x
			right.y = 0.0
			right = right.normalized()
			xr_origin.position += (fwd * mv.y + right * mv.x) * XR_MOVE_SPEED * delta
	# Right stick X: comfortable snap turns.
	if xr_right != null:
		var tv := xr_right.get_vector2("primary")
		if absf(tv.x) > 0.7 and _xr_snap_ready:
			xr_origin.rotate_y(deg_to_rad(-signf(tv.x) * XR_SNAP_DEG))
			_xr_snap_ready = false
		elif absf(tv.x) < 0.3:
			_xr_snap_ready = true


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
	# Phi-cutaway parameters shared by every detector material, plus the
	# event propagation-reveal front (huge = everything visible).
	for params in [["cv_phi_min", phi_min], ["cv_phi_max", phi_max],
			["cv_cutaway_enabled", 1.0 if cutaway_enabled else 0.0],
			["cv_event_reveal", 1e9]]:
		RenderingServer.global_shader_parameter_add(
			params[0], RenderingServer.GLOBAL_VAR_TYPE_FLOAT, params[1])


func _build_environment() -> void:
	var env := Environment.new()

	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.008, 0.011, 0.018)

	# Soft cool ambient — stands in for the dome's even illumination.
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.72, 0.80, 0.92)
	env.ambient_light_energy = 0.26

	if is_mobile:
		# Quest / phone run the Forward Mobile renderer, which supports none of
		# the GI or screen-space effects below — and if a Forward+ path ever
		# leaks onto the headset they are an instant frame-rate sentence
		# (SDFGI alone ray-marches every pixel). Force them all off and lean on
		# a brighter flat ambient instead. Tonemap + colour grade still apply.
		env.ambient_light_energy = 0.6
		env.sdfgi_enabled = false
		env.ssao_enabled = false
		env.ssil_enabled = false
		env.ssr_enabled = false
		env.glow_enabled = false
		env.volumetric_fog_enabled = false
	else:
		# Real-time global illumination: light bounces off the hall and the
		# detector's metal surfaces; emissive tracks tint their surroundings.
		env.sdfgi_enabled = true
		env.sdfgi_use_occlusion = true
		env.sdfgi_bounce_feedback = 0.6
		env.sdfgi_cascades = 4
		env.sdfgi_min_cell_size = 0.12
		env.sdfgi_energy = 1.1

		# Contact shadows in detector crevices. SSIL is expensive and off by
		# default ("Quality" preset re-enables it) — VoxelGI covers indirect.
		# Gentle AO — strong settings read as dirty/noisy splotches on the
		# clean surfaces; the baked GI already grounds the geometry.
		env.ssao_enabled = true
		env.ssao_radius = 1.2
		env.ssao_intensity = 1.1
		env.ssao_power = 1.5
		env.ssil_enabled = false
		env.ssil_radius = 3.0
		env.ssil_intensity = 1.0

		# Screen-space reflections on the polished metal and the glass floor.
		env.ssr_enabled = true
		env.ssr_max_steps = 48
		env.ssr_fade_in = 0.15
		env.ssr_fade_out = 2.0
		env.ssr_depth_tolerance = 0.4

		# Bloom — restrained: only genuinely hot emissives (tracks, hit cores)
		# halo, and only gently.
		env.glow_enabled = true
		env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SCREEN
		env.glow_intensity = 0.55
		env.glow_strength = 0.95
		env.glow_bloom = 0.0
		env.glow_hdr_threshold = 1.5
		env.set_glow_level(1, 0.5)
		env.set_glow_level(2, 0.8)
		env.set_glow_level(3, 1.0)
		env.set_glow_level(4, 0.55)
		env.set_glow_level(5, 0.3)

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
	# The Mobile renderer (Quest) supports neither VoxelGI nor SDFGI;
	# ambient + direct light carry the scene there.
	if RenderingServer.get_current_rendering_method() != "forward_plus":
		return
	voxel_gi = VoxelGI.new()
	voxel_gi.name = "VoxelGI"
	# Cover the hall with some headroom; subdiv 256 -> ~16 cm voxels.
	# Cover the detector + the walkable area around it (the dome itself
	# stays outside the field; it's ambient-lit, not GI-driven).
	voxel_gi.size = Vector3(RIG_HALF_X * 2.0 + 2.0, 17.0, RIG_HALF_Z * 2.0 + 2.0)
	voxel_gi.position = Vector3(0, 1.0, 0)
	# 128³ halves the per-pixel cone-trace cost vs 256³ and bakes in a
	# fraction of the time; with GI at half resolution the visual
	# difference on a 9 m detector is minor.
	voxel_gi.subdiv = VoxelGI.SUBDIV_128
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
# Stage — softly lit dome + infinite glass floor at the beam plane (y = 0)
# ──────────────────────────────────────────────────────────────────────────────

func _build_stage() -> void:
	# Smooth gradient dome, seen from inside.
	var dome_mesh := SphereMesh.new()
	dome_mesh.radius = DOME_RADIUS
	dome_mesh.height = DOME_RADIUS * 2.0
	dome = MeshInstance3D.new()
	dome.name = "Dome"
	dome.mesh = dome_mesh
	var dome_mat := ShaderMaterial.new()
	dome_mat.shader = load("res://shaders/dome.gdshader")
	dome.material_override = dome_mat
	dome.gi_mode = GeometryInstance3D.GI_MODE_DISABLED
	dome.extra_cull_margin = DOME_RADIUS   # never frustum-culled from inside
	add_child(dome)

	# Glass floor through the detector mid-plane: walk up to the IP, look
	# down at the lower barrel half through the glass.
	var plane := PlaneMesh.new()
	plane.size = Vector2(DOME_RADIUS * 2.2, DOME_RADIUS * 2.2)
	var glass := MeshInstance3D.new()
	glass.name = "GlassFloor"
	glass.mesh = plane
	var gm := StandardMaterial3D.new()
	gm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	gm.albedo_color = Color(0.75, 0.85, 0.95, 0.022)   # barely-there
	gm.metallic = 0.0
	# Specular survives alpha transparency at full strength, so the glass
	# needs a genuinely soft, weak sheen or every spot blows out on it.
	gm.roughness = 0.4
	gm.metallic_specular = 0.04
	gm.cull_mode = BaseMaterial3D.CULL_DISABLED   # visible from below too
	glass.material_override = gm
	glass.gi_mode = GeometryInstance3D.GI_MODE_DISABLED
	glass.position = Vector3.ZERO
	# Only rendered in third-person mode — orbit/fly views see no floor at
	# all (the collision plane below stays active regardless; it's only
	# ever felt by the character).
	glass.visible = false
	glass_floor = glass
	add_child(glass)

	# Infinite walkable plane (collision only) at y = 0.
	var body := StaticBody3D.new()
	body.name = "GlassFloorBody"
	var shape := CollisionShape3D.new()
	shape.shape = WorldBoundaryShape3D.new()
	body.add_child(shape)
	add_child(body)


# ──────────────────────────────────────────────────────────────────────────────
# Light rig — symmetric warm blackbody softbox array
# ──────────────────────────────────────────────────────────────────────────────

## Planckian-locus colour for a blackbody emitter (Tanner Helland fit).
static func blackbody(kelvin: float) -> Color:
	var t := clampf(kelvin, 1000.0, 12000.0) / 100.0
	var r: float
	var g: float
	var b: float
	if t <= 66.0:
		r = 255.0
		g = clampf(99.4708025861 * log(t) - 161.1195681661, 0.0, 255.0)
		if t <= 19.0:
			b = 0.0
		else:
			b = clampf(138.5177312231 * log(t - 10.0) - 305.0447927307, 0.0, 255.0)
	else:
		r = clampf(329.698727446 * pow(t - 60.0, -0.1332047592), 0.0, 255.0)
		g = clampf(288.1221695283 * pow(t - 60.0, -0.0755148492), 0.0, 255.0)
		b = 255.0
	return Color(r / 255.0, g / 255.0, b / 255.0)

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
		range_m: float, size: float, fog_energy: float,
		shadows := true) -> SpotLight3D:
	var l := SpotLight3D.new()
	l.position = pos
	l.light_color = color
	l.light_energy = energy
	l.spot_angle = angle_deg
	l.spot_range = range_m
	l.light_size = size * 1.8   # bigger virtual source = softer penumbrae
	l.shadow_enabled = shadows
	if shadows:
		_shadow_casters.append(l)
	l.shadow_blur = 3.0
	l.light_volumetric_fog_energy = fog_energy
	l.light_specular = 0.8
	add_child(l)
	l.look_at_from_position(pos, Vector3.ZERO, Vector3.UP if absf(pos.normalized().y) < 0.95 else Vector3.FORWARD)
	rig_lights.append([l, energy])
	l.light_energy = energy * light_scale
	return l


func _build_light_rig() -> void:
	# Everything sits on the blackbody locus — a warm studio. Placement is
	# fully symmetric under x -> -x and z -> -z.
	var key_color := blackbody(4100.0)     # overhead softboxes
	var side_color := blackbody(4800.0)    # neutral-warm side strips
	var end_color := blackbody(4500.0)     # end panels down the beam axis
	var under_color := blackbody(3400.0)   # faint warm under-glow

	if is_mobile:
		# Forward Mobile does per-pixel lighting; with the cull_disabled
		# detector overdraw, every extra light is a big fragment cost on the
		# Quest. Run a minimal shadowless fill rig (the brighter ambient set in
		# _build_environment carries the rest) instead of the 10-light studio.
		_add_spot(Vector3(-5.5, RIG_CEIL_Y - 0.2, 0.0), key_color, 60.0, 120.0, 45.0, 1.4, 0.0, false)
		_add_spot(Vector3(5.5, RIG_CEIL_Y - 0.2, 0.0), key_color, 60.0, 120.0, 45.0, 1.4, 0.0, false)
		_add_spot(Vector3(0.0, 4.0, 9.0), end_color, 45.0, 110.0, 45.0, 1.0, 0.0, false)
		ip_light = OmniLight3D.new()
		ip_light.position = Vector3.ZERO
		ip_light.light_color = Color(1.0, 0.72, 0.42)
		ip_light.light_energy = 0.0
		ip_light.omni_range = 11.0
		ip_light.shadow_enabled = false
		add_child(ip_light)
		return

	# Four overhead softbox panels in a symmetric 2x2 array.
	for sx in [-1.0, 1.0]:
		for sz in [-1.0, 1.0]:
			var p := Vector3(sx * 5.5, RIG_CEIL_Y - 0.2, sz * 6.5)
			_add_spot(p, key_color, 42.0, 110.0, 35.0, 1.4, 0.4)
			_add_fixture_panel(Vector3(p.x, RIG_CEIL_Y + 0.1, p.z),
				Vector3(3.0, 0.1, 2.2), key_color, 2.0)

	# Long strip softboxes on both ±X sides (no shadow maps — fill only).
	for sx in [-1.0, 1.0]:
		var p := Vector3(sx * (RIG_HALF_X - 0.3), 2.5, 0.0)
		_add_spot(p, side_color, 40.0, 120.0, 30.0, 1.0, 0.3, false)
		_add_fixture_panel(Vector3(sx * (RIG_HALF_X + 0.1), 2.5, 0.0),
			Vector3(0.1, 0.5, 12.0), side_color, 1.6)

	# Matching end panels on ±Z so the barrel faces never go black.
	for sz in [-1.0, 1.0]:
		var p := Vector3(0.0, 5.0, sz * (RIG_HALF_Z - 0.5))
		_add_spot(p, end_color, 30.0, 100.0, 34.0, 1.0, 0.2, false)
		_add_fixture_panel(Vector3(0.0, 5.0, sz * (RIG_HALF_Z + 0.1)),
			Vector3(4.0, 2.6, 0.1), end_color, 1.4)

	# Faint warm under-glow below the glass so the lower half reads.
	var under := OmniLight3D.new()
	under.position = Vector3(0, -5.5, 0)
	under.light_color = under_color
	under.light_energy = 4.0
	under.omni_range = 14.0
	under.shadow_enabled = false
	under.light_volumetric_fog_energy = 0.15
	add_child(under)
	rig_lights.append([under, 4.0])
	under.light_energy = 4.0 * light_scale

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
	_shadow_casters.append(ip_light)


# ──────────────────────────────────────────────────────────────────────────────
# Geometry
# ──────────────────────────────────────────────────────────────────────────────

## The repo-level gltf/ directory is the canonical geometry source when
## running from source; exported builds carry a copy in assets/detector
## (placed there by CI before the export).
func _default_geometry_dir() -> String:
	for d in ["res://../gltf", DEFAULT_GEOMETRY_DIR]:
		var da := DirAccess.open(d)
		if da != null:
			for f in da.get_files():
				var ext := f.get_extension().to_lower()
				if ext == "gltf" or ext == "glb":
					return d
	return DEFAULT_GEOMETRY_DIR


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
	event_display.visible = show_events
	ip_light.light_energy = 2.0 if show_events else 0.0
	if show_events:
		event_display.play_emergence()
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
# Settings (driven by the UI settings panel)
# ──────────────────────────────────────────────────────────────────────────────

const RESOLUTIONS := [
	Vector2i(1280, 720), Vector2i(1600, 900),
	Vector2i(1920, 1080), Vector2i(2560, 1440), Vector2i(3840, 2160)]


func set_light_scale(f: float) -> void:
	light_scale = f
	for entry in rig_lights:
		(entry[0] as Light3D).light_energy = float(entry[1]) * f


func set_dof_amount(amount: float) -> void:
	for cam in [orbit_camera, character.camera if character != null else null]:
		if cam != null and cam.attributes is CameraAttributesPractical:
			var a := cam.attributes as CameraAttributesPractical
			a.dof_blur_far_enabled = amount > 0.001
			a.dof_blur_amount = amount


func get_dof_amount() -> float:
	if orbit_camera.attributes is CameraAttributesPractical:
		return (orbit_camera.attributes as CameraAttributesPractical).dof_blur_amount
	return 0.0


## Post-FX shader parameters (lens flares, motion blur, CA, grain, vignette).
func set_fx_param(param: String, value: float) -> void:
	if post_fx_mat != null:
		post_fx_mat.set_shader_parameter(param, value)


func get_fx_param(param: String) -> float:
	if post_fx_mat != null:
		var v: Variant = post_fx_mat.get_shader_parameter(param)
		if v != null:
			return float(v)
	return 0.0


func set_event_display_visible(on: bool) -> void:
	show_events = on
	if event_display != null:
		event_display.visible = on
	ip_light.light_energy = 2.0 if (on and event_display != null) else 0.0
	_ui_refresh()


func set_render_scale(f: float) -> void:
	var vp := get_viewport()
	vp.scaling_3d_scale = clampf(f, 0.5, 1.0)
	# FSR2 reconstructs near-native sharpness from the reduced-scale frame
	# (plain bilinear reads soft/pixelated); it supplies its own temporal
	# accumulation, so TAA goes off with it. Not available in XR or on the
	# Mobile renderer — those stay on plain bilinear scaling.
	var can_fsr2 := not vp.use_xr \
		and RenderingServer.get_current_rendering_method() == "forward_plus"
	if vp.scaling_3d_scale < 0.999 and can_fsr2:
		vp.scaling_3d_mode = Viewport.SCALING_3D_MODE_FSR2
		vp.use_taa = false
	else:
		vp.scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
		vp.use_taa = not is_mobile


func set_resolution_index(idx: int) -> void:
	if idx < 0 or idx >= RESOLUTIONS.size():
		return
	if DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_FULLSCREEN:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)
	DisplayServer.window_set_size(RESOLUTIONS[idx])
	# Re-centre on the current screen.
	var screen := DisplayServer.window_get_current_screen()
	var srect := DisplayServer.screen_get_usable_rect(screen)
	DisplayServer.window_set_position(
		srect.position + (srect.size - RESOLUTIONS[idx]) / 2)


func set_fullscreen(on: bool) -> void:
	DisplayServer.window_set_mode(
		DisplayServer.WINDOW_MODE_FULLSCREEN if on else DisplayServer.WINDOW_MODE_WINDOWED)


## Quality presets tune the expensive per-frame effects. VoxelGI (baked)
## stays on in all of them.
func apply_quality(preset: String) -> void:
	var vp := get_viewport()
	match preset:
		"performance":
			environment.ssil_enabled = false
			environment.ssr_enabled = false
			environment.ssao_enabled = false
			environment.volumetric_fog_enabled = false
			# Real-time shadow maps re-render the whole 1.8M-tri detector once
			# per shadow-casting light — ruinous on the Quest tiler GPU. Drop
			# them (and glow) in performance mode; the ambient + direct light
			# rig still reads fine.
			_set_shadows(false)
			environment.glow_enabled = false
			vp.msaa_3d = Viewport.MSAA_2X if get_viewport().use_xr else Viewport.MSAA_DISABLED
		"balanced":
			environment.ssil_enabled = false
			environment.ssr_enabled = true
			environment.ssr_max_steps = 48
			environment.ssao_enabled = true
			environment.volumetric_fog_enabled = true
			_set_shadows(true)
			environment.glow_enabled = true
			vp.msaa_3d = Viewport.MSAA_2X
		"quality":
			environment.ssil_enabled = true
			environment.ssr_enabled = true
			environment.ssr_max_steps = 96
			environment.ssao_enabled = true
			environment.volumetric_fog_enabled = true
			_set_shadows(true)
			environment.glow_enabled = true
			vp.msaa_3d = Viewport.MSAA_4X


func _set_shadows(on: bool) -> void:
	for l in _shadow_casters:
		if is_instance_valid(l):
			(l as Light3D).shadow_enabled = on


## Aggressive mesh LOD on phones/headsets: a low lod_bias drops to coarser
## auto-generated LODs at much shorter distances, trimming the ~1.9M-tri
## detector for everything that isn't right in front of you. No-op if the
## imported meshes carry no LOD chain.
func _optimize_geometry_for_mobile() -> void:
	for g in detector_groups:
		for node in detector_groups[g]:
			_set_lod_bias_recursive(node as Node, 0.35)


func _set_lod_bias_recursive(node: Node, bias: float) -> void:
	if node is MeshInstance3D:
		(node as MeshInstance3D).lod_bias = bias
	for c in node.get_children():
		_set_lod_bias_recursive(c, bias)


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
			if is_mobile:
				# No keys for flying — go straight to the walkable mode
				# (virtual joystick + jump button take over there).
				cam_mode = CamMode.FLY   # fall through to WALK below
				cycle_camera_mode()
				return
			cam_mode = CamMode.FLY
			orbit_camera.set_fly(true)
		CamMode.FLY:
			cam_mode = CamMode.WALK
			orbit_camera.set_fly(false)
			if character == null:
				character = Character.new()
				character.name = "Explorer"
				# On the glass floor at the beam plane, facing the IP.
				character.position = Vector3(9.5, 0.1, 4.0)
				add_child(character)
			character.visible = true
			character.camera.current = true
		CamMode.WALK:
			cam_mode = CamMode.ORBIT
			if character != null:
				character.visible = false
			orbit_camera.current = true
	# The glass floor is a third-person-only cue.
	if glass_floor != null:
		glass_floor.visible = (cam_mode == CamMode.WALK)
	_sync_mouse_mode()
	_ui_refresh()


func toggle_menu_request() -> void:
	ui.toggle_menu()
	_sync_mouse_mode()


## Cursor policy: menu open = free cursor; menu closed = captured mouse
## driving whichever camera is active.
func _sync_mouse_mode() -> void:
	if _args.has("screenshot"):
		return
	if ui != null and ui.is_menu_open():
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	else:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


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
	# The many-tap lens pass is poison for mobile tiler GPUs.
	layer.visible = not is_mobile
	add_child(layer)


func _process(_delta: float) -> void:
	_process_xr(_delta)
	# The lens/motion-blur post pass is disabled on mobile (post_fx layer is
	# hidden), so don't waste per-frame work computing motion vectors for it.
	if is_mobile:
		return
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


func _unhandled_input(event: InputEvent) -> void:
	# LMB click (while the captured mouse is driving a camera) = next event.
	var mb := event as InputEventMouseButton
	if mb != null and mb.pressed and mb.button_index == MOUSE_BUTTON_LEFT \
			and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		show_relative_event(1)


func _unhandled_key_input(event: InputEvent) -> void:
	var k := event as InputEventKey
	if k == null or not k.pressed or k.echo:
		return
	match k.keycode:
		KEY_ESCAPE:
			ui.toggle_menu()
			_sync_mouse_mode()
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
	# This path runs in CI on Mesa's software Vulkan (lavapipe), where the
	# FSR2 upscaling compute pass costs far more than it saves and can stall
	# the smoke test past its timeout. Render at native scale with plain
	# bilinear (no FSR2, no TAA accumulation) so each frame is cheap; the
	# baked VoxelGI is kept so the screenshot still shows real lighting.
	var vp := get_viewport()
	vp.scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
	vp.scaling_3d_scale = 1.0
	vp.use_taa = false
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
