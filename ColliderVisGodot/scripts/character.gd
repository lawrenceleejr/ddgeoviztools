extends CharacterBody3D
## Third-person explorer at true human scale (~1.8 m) so the detector reads
## at its real, overwhelming size.
##
## Primary body: the GDQuest "Mannequiny" rigged character (CC-BY 4.0,
## attribution on the in-game credits screen and in
## assets/character/CREDITS_GDQUEST.txt) with its idle / run / jump / land
## animation clips, cross-blended and speed-matched to ground velocity.
##
## Fallback body (if the model file is removed): a procedurally built
## "cavern physicist" — hard hat, hi-vis vest, glowing atom emblem — with a
## procedural walk cycle.
##
## Movement à la UE's third-person template: WASD relative to the camera,
## Shift runs, Space jumps, the body turns toward the move direction.

const MODEL_PATH := "res://assets/character/mannequiny.glb"
## Mannequiny faces +Z, matching the rig math below (atan2(dir.x, dir.z)).
const MODEL_YAW_OFFSET := 0.0
const BLEND_TIME := 0.25

const BASE_FOV := 65.0
const ZOOM_FOV := 36.0
const BASE_ARM := 4.0
const ZOOM_ARM := 1.4   # body hides while zoomed, so tuck right in

const WALK_SPEED := 3.0
const RUN_SPEED := 6.5
const JUMP_VELOCITY := 4.8
const GRAVITY := 12.0
const TURN_LERP := 10.0
const LOOK_SPEED := 0.0035

var cam_yaw := 1.16    # spawn looking at the detector from the default spawn point
var cam_pitch := -0.12
var _phase := 0.0
var _speed_blend := 0.0   # 0 idle .. 1 run, smoothed

# Rig pivots (model front = +Z).
var rig: Node3D
var torso: Node3D
var head: Node3D
var hip_l: Node3D
var hip_r: Node3D
var knee_l: Node3D
var knee_r: Node3D
var shoulder_l: Node3D
var shoulder_r: Node3D
var elbow_l: Node3D
var elbow_r: Node3D

var spring: SpringArm3D
var camera: Camera3D

# Rigged-model state (null anim => procedural fallback drives the pivots).
var anim: AnimationPlayer = null
var _current_clip := ""
var _was_airborne := false
var _land_timer := 0.0


func _ready() -> void:
	rig = Node3D.new()
	add_child(rig)
	rig.rotation.y = cam_yaw + PI   # face away from the camera at spawn
	if not _load_model():
		_build_body()
	_build_camera()
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.3
	capsule.height = 1.75
	shape.shape = capsule
	shape.position = Vector3(0, 0.875, 0)
	add_child(shape)


# ── rigged model ─────────────────────────────────────────────────────────────

func _load_model() -> bool:
	var scene: Node = null
	if ResourceLoader.exists(MODEL_PATH, "PackedScene"):
		var ps: PackedScene = load(MODEL_PATH)
		if ps != null:
			scene = ps.instantiate()
	if scene == null and FileAccess.file_exists(MODEL_PATH):
		var doc := GLTFDocument.new()
		var state := GLTFState.new()
		if doc.append_from_file(MODEL_PATH, state) == OK:
			scene = doc.generate_scene(state)
	if scene == null:
		push_warning("Character: '%s' unavailable; using procedural body." % MODEL_PATH)
		return false
	var holder := Node3D.new()
	holder.rotation.y = MODEL_YAW_OFFSET
	holder.add_child(scene)
	rig.add_child(holder)
	for mi in scene.find_children("*", "MeshInstance3D", true, false):
		(mi as GeometryInstance3D).gi_mode = GeometryInstance3D.GI_MODE_DYNAMIC
	var players := scene.find_children("*", "AnimationPlayer", true, false)
	if players.is_empty():
		push_warning("Character: no AnimationPlayer in model; using procedural body.")
		holder.queue_free()
		return false
	anim = players[0]
	for clip in ["idle", "run"]:
		if anim.has_animation(clip):
			anim.get_animation(clip).loop_mode = Animation.LOOP_LINEAR
	_play("idle")
	return true


func _play(clip: String, speed := 1.0) -> void:
	if anim == null or not anim.has_animation(clip):
		return
	if _current_clip != clip:
		anim.play(clip, BLEND_TIME)
		_current_clip = clip
	anim.speed_scale = speed


# ── procedural physicist (fallback body) ─────────────────────────────────────

func _mat(color: Color, roughness := 0.85, metallic := 0.0,
		emissive := Color.BLACK, e_energy := 0.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	m.metallic = metallic
	m.roughness = roughness
	if e_energy > 0.0:
		m.emission_enabled = true
		m.emission = emissive
		m.emission_energy_multiplier = e_energy
	return m


func _part(parent: Node3D, mesh: Mesh, pos: Vector3, mat: Material,
		rot := Vector3.ZERO) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.position = pos
	mi.rotation = rot
	mi.material_override = mat
	mi.gi_mode = GeometryInstance3D.GI_MODE_DYNAMIC   # moves; never bake
	parent.add_child(mi)
	return mi


func _pivot(parent: Node3D, pos: Vector3) -> Node3D:
	var p := Node3D.new()
	p.position = pos
	parent.add_child(p)
	return p


func _capsule(radius: float, height: float) -> CapsuleMesh:
	var c := CapsuleMesh.new()
	c.radius = radius
	c.height = height
	return c


func _box(size: Vector3) -> BoxMesh:
	var b := BoxMesh.new()
	b.size = size
	return b


func _sphere(radius: float) -> SphereMesh:
	var s := SphereMesh.new()
	s.radius = radius
	s.height = radius * 2.0
	return s


func _build_body() -> void:
	var skin := _mat(Color(0.85, 0.62, 0.48), 0.75)
	var vest := _mat(Color(0.95, 0.33, 0.04), 0.85)            # hi-vis orange
	var stripe := _mat(Color(0.85, 0.78, 0.15), 0.5, 0.0,
		Color(1.0, 0.92, 0.25), 1.3)                            # reflective band
	var coverall := _mat(Color(0.17, 0.21, 0.30), 0.9)          # work blues
	var boots := _mat(Color(0.07, 0.07, 0.08), 0.6)
	var hat := _mat(Color(0.93, 0.93, 0.96), 0.35)              # white hard hat
	var hair := _mat(Color(0.16, 0.11, 0.07), 0.9)
	var glow := _mat(Color(0.05, 0.10, 0.15), 0.4, 0.0,
		Color(0.15, 0.75, 1.0), 3.0)                            # cyan atom accent

	# Pelvis + torso (rig origin at the feet; front = +Z).
	var pelvis := _pivot(rig, Vector3(0, 1.0, 0))
	_part(pelvis, _box(Vector3(0.30, 0.18, 0.19)), Vector3(0, -0.02, 0), coverall)
	torso = _pivot(pelvis, Vector3(0, 0.08, 0))
	_part(torso, _capsule(0.155, 0.52), Vector3(0, 0.26, 0), coverall)
	# Hi-vis vest worn over the torso, with reflective stripes.
	_part(torso, _box(Vector3(0.36, 0.36, 0.235)), Vector3(0, 0.28, 0), vest)
	for sx in [-0.09, 0.09]:
		_part(torso, _box(Vector3(0.055, 0.365, 0.24)), Vector3(sx, 0.28, 0), stripe)
	_part(torso, _box(Vector3(0.365, 0.05, 0.24)), Vector3(0, 0.14, 0), stripe)
	# Atom emblem on the back of the vest: nucleus + three electron rings.
	var emblem := _pivot(torso, Vector3(0, 0.32, -0.135))
	_part(emblem, _sphere(0.022), Vector3.ZERO, glow)
	var ring := TorusMesh.new()
	ring.inner_radius = 0.062
	ring.outer_radius = 0.072
	for rz in [0.0, PI / 3.0, -PI / 3.0]:
		_part(emblem, ring, Vector3.ZERO, glow, Vector3(PI / 2.0, 0, rz))

	# Head: neck, face (eyes toward +Z), hair, hard hat with brim.
	head = _pivot(torso, Vector3(0, 0.52, 0))
	_part(head, _capsule(0.045, 0.10), Vector3(0, 0.02, 0), skin)
	_part(head, _sphere(0.105), Vector3(0, 0.135, 0.005), skin)
	for sx in [-0.038, 0.038]:
		_part(head, _sphere(0.012), Vector3(sx, 0.155, 0.095), boots)  # eyes
	_part(head, _sphere(0.012), Vector3(0, 0.125, 0.108), skin)        # nose
	var hair_cap := _sphere(0.107)
	_part(head, hair_cap, Vector3(0, 0.155, -0.025), hair)
	var dome := CylinderMesh.new()
	dome.top_radius = 0.09
	dome.bottom_radius = 0.125
	dome.height = 0.085
	_part(head, dome, Vector3(0, 0.235, 0.0), hat)
	var brim := CylinderMesh.new()
	brim.top_radius = 0.155
	brim.bottom_radius = 0.155
	brim.height = 0.018
	_part(head, brim, Vector3(0, 0.195, 0.01), hat)

	# Arms (skin hands, coverall sleeves with hi-vis cuff).
	shoulder_l = _pivot(torso, Vector3(-0.225, 0.45, 0))
	shoulder_r = _pivot(torso, Vector3(0.225, 0.45, 0))
	for s in [shoulder_l, shoulder_r]:
		_part(s, _capsule(0.052, 0.28), Vector3(0, -0.14, 0), coverall)
	elbow_l = _pivot(shoulder_l, Vector3(0, -0.30, 0))
	elbow_r = _pivot(shoulder_r, Vector3(0, -0.30, 0))
	for e in [elbow_l, elbow_r]:
		_part(e, _capsule(0.045, 0.24), Vector3(0, -0.12, 0), coverall)
		_part(e, _box(Vector3(0.10, 0.045, 0.10)), Vector3(0, -0.20, 0), stripe)
		_part(e, _sphere(0.048), Vector3(0, -0.27, 0), skin)   # hand

	# Legs with knees and safety boots.
	hip_l = _pivot(pelvis, Vector3(-0.095, -0.08, 0))
	hip_r = _pivot(pelvis, Vector3(0.095, -0.08, 0))
	for hp in [hip_l, hip_r]:
		_part(hp, _capsule(0.072, 0.40), Vector3(0, -0.20, 0), coverall)
	knee_l = _pivot(hip_l, Vector3(0, -0.44, 0))
	knee_r = _pivot(hip_r, Vector3(0, -0.44, 0))
	for kn in [knee_l, knee_r]:
		_part(kn, _capsule(0.058, 0.36), Vector3(0, -0.18, 0), coverall)
		_part(kn, _box(Vector3(0.105, 0.10, 0.26)), Vector3(0, -0.43, 0.045), boots)


# ── camera ───────────────────────────────────────────────────────────────────

func _build_camera() -> void:
	# Over-the-shoulder cinematic follow camera.
	var gimbal := Node3D.new()
	gimbal.name = "Gimbal"
	gimbal.position = Vector3(0, 1.55, 0)
	add_child(gimbal)
	spring = SpringArm3D.new()
	spring.spring_length = 4.0
	spring.collision_mask = 1
	gimbal.add_child(spring)
	camera = Camera3D.new()
	camera.fov = 65.0
	camera.near = 0.05
	camera.position = Vector3(0.45, 0.15, 0)   # slight shoulder offset
	var attrs := CameraAttributesPractical.new()
	attrs.dof_blur_far_enabled = true
	attrs.dof_blur_far_distance = 18.0
	attrs.dof_blur_far_transition = 14.0
	attrs.dof_blur_amount = 0.04
	camera.attributes = attrs
	spring.add_child(camera)


# ── control & animation ──────────────────────────────────────────────────────

func _unhandled_input(event: InputEvent) -> void:
	if not camera.current:
		return
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		var mm := event as InputEventMouseMotion
		var sens := LOOK_SPEED * camera.fov / BASE_FOV   # tighter while zoomed
		cam_yaw -= mm.relative.x * sens
		cam_pitch = clampf(cam_pitch - mm.relative.y * sens, -1.2, 0.5)


func _physics_process(delta: float) -> void:
	if not camera.current:
		return

	# Camera gimbal.
	var gimbal := spring.get_parent() as Node3D
	gimbal.rotation = Vector3(cam_pitch, cam_yaw, 0)

	# Hold-RMB examine zoom: FOV push-in + the arm tucks in. The body gets
	# out of the way: it vanishes early in the zoom-in and reappears as the
	# zoom eases back out.
	var zooming := Input.mouse_mode == Input.MOUSE_MODE_CAPTURED \
		and Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT)
	var zk := 1.0 - exp(-8.0 * delta)
	camera.fov = lerpf(camera.fov, ZOOM_FOV if zooming else BASE_FOV, zk)
	spring.spring_length = lerpf(spring.spring_length, ZOOM_ARM if zooming else BASE_ARM, zk)
	rig.visible = not (zooming and camera.fov < BASE_FOV - 6.0)

	# Movement relative to camera yaw.
	var input_dir := Vector2.ZERO
	if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		if Input.is_key_pressed(KEY_W): input_dir.y += 1
		if Input.is_key_pressed(KEY_S): input_dir.y -= 1
		if Input.is_key_pressed(KEY_A): input_dir.x -= 1
		if Input.is_key_pressed(KEY_D): input_dir.x += 1
	var running := Input.is_key_pressed(KEY_SHIFT)
	var speed := RUN_SPEED if running else WALK_SPEED

	var fwd := Vector3(-sin(cam_yaw), 0, -cos(cam_yaw))
	var right := Vector3(cos(cam_yaw), 0, -sin(cam_yaw))
	var wish := (fwd * input_dir.y + right * input_dir.x)
	if wish.length() > 0.01:
		wish = wish.normalized()
		velocity.x = wish.x * speed
		velocity.z = wish.z * speed
		rig.rotation.y = lerp_angle(rig.rotation.y, atan2(wish.x, wish.z), TURN_LERP * delta)
	else:
		velocity.x = move_toward(velocity.x, 0, speed * 4.0 * delta)
		velocity.z = move_toward(velocity.z, 0, speed * 4.0 * delta)

	var jumped := false
	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	elif Input.is_key_pressed(KEY_SPACE) and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		velocity.y = JUMP_VELOCITY
		jumped = true

	move_and_slide()
	if anim != null:
		_animate_clips(delta, jumped)
	else:
		_animate(delta)


func _animate_clips(delta: float, jumped: bool) -> void:
	var airborne := not is_on_floor()
	var ground_speed := Vector2(velocity.x, velocity.z).length()
	if jumped or airborne:
		_play("air_jump")
	elif _was_airborne:
		_play("air_land")
		_land_timer = 0.2
	elif _land_timer > 0.0:
		_land_timer -= delta
	elif ground_speed > 0.25:
		# Single locomotion clip: scale playback so a slow walk doesn't
		# look like running on ice (run clip is authored for RUN_SPEED).
		_play("run", clampf(ground_speed / RUN_SPEED, 0.45, 1.25))
	else:
		_play("idle")
	_was_airborne = airborne


func _animate(delta: float) -> void:
	var ground_speed := Vector2(velocity.x, velocity.z).length()
	var target_blend := clampf(ground_speed / RUN_SPEED, 0.0, 1.0)
	_speed_blend = lerpf(_speed_blend, target_blend, 8.0 * delta)
	# Stride frequency follows actual speed so feet plant rather than slide.
	_phase += delta * (2.0 + 9.0 * _speed_blend)

	var k := _speed_blend
	var swing := sin(_phase)
	var swing2 := sin(_phase + PI)

	# Legs: thighs swing in opposition; knees bend on the back-swing.
	hip_l.rotation.x = swing * 0.75 * k
	hip_r.rotation.x = swing2 * 0.75 * k
	knee_l.rotation.x = -maxf(0.0, -swing) * 1.1 * k
	knee_r.rotation.x = -maxf(0.0, -swing2) * 1.1 * k

	# Arms counter-swing; idle has a subtle sway.
	var idle_sway := sin(_phase * 0.35) * 0.04
	shoulder_l.rotation.x = swing2 * 0.55 * k + idle_sway
	shoulder_r.rotation.x = swing * 0.55 * k - idle_sway
	elbow_l.rotation.x = -0.25 - maxf(0.0, swing2) * 0.5 * k
	elbow_r.rotation.x = -0.25 - maxf(0.0, swing) * 0.5 * k

	# Torso: bob + slight lean into the run; idle breathing.
	var bob := absf(cos(_phase)) * 0.05 * k
	torso.position.y = 0.08 + bob + sin(_phase * 0.5) * 0.008 * (1.0 - k)
	torso.rotation.x = -0.12 * k
	head.rotation.x = 0.10 * k   # keep the gaze level-ish while leaning
