extends CharacterBody3D
## Third-person explorer: a fully rigged, professionally animated character
## (KayKit "Adventurers" Knight — CC0, see assets/character/KAYKIT_LICENSE.txt)
## driven à la UE's third-person template: WASD moves relative to the camera,
## Shift runs, Space jumps, the body turns toward the move direction.
##
## Locomotion uses the pack's animation library with cross-blending:
## Idle / Walking_B / Running_B on the ground (playback speed scaled to
## actual velocity so feet don't slide), Jump_Start → Jump_Idle → Jump_Land
## in the air. If the model file is missing (e.g. a stripped fork), a simple
## capsule keeps the mode functional.

const MODEL_PATH := "res://assets/character/Knight.glb"
## Prop nodes hidden at runtime — our explorer is unarmed, and the cape
## blocks the whole torso from the over-the-shoulder camera.
const HIDDEN_PROPS := ["1H_Sword", "1H_Sword_Offhand", "2H_Sword",
	"Badge_Shield", "Rectangle_Shield", "Round_Shield", "Spike_Shield",
	"Knight_Cape"]
## Looping locomotion clips (imported glTF clips default to one-shot).
const LOOPED_CLIPS := ["Idle", "Walking_B", "Running_B", "Jump_Idle"]
## KayKit models face +Z; rig yaw is atan2(dir.x, dir.z) + this offset.
const MODEL_YAW_OFFSET := 0.0

const WALK_SPEED := 3.0
const RUN_SPEED := 6.5
const JUMP_VELOCITY := 4.8
const GRAVITY := 12.0
const TURN_LERP := 10.0
const LOOK_SPEED := 0.0035
const BLEND_TIME := 0.25

var cam_yaw := 1.16    # spawn looking at the detector from the default spawn point
var cam_pitch := -0.12

var rig: Node3D
var anim: AnimationPlayer = null
var spring: SpringArm3D
var camera: Camera3D

var _current_clip := ""
var _was_airborne := false
var _land_timer := 0.0


func _ready() -> void:
	rig = Node3D.new()
	add_child(rig)
	rig.rotation.y = cam_yaw + PI + MODEL_YAW_OFFSET   # face away from camera
	if not _load_model():
		_build_fallback_body()
	_build_camera()
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.3
	capsule.height = 1.7
	shape.shape = capsule
	shape.position = Vector3(0, 0.85, 0)
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
		push_warning("Character: model '%s' unavailable; using capsule." % MODEL_PATH)
		return false
	rig.add_child(scene)
	for prop_name in HIDDEN_PROPS:
		var n := scene.find_child(prop_name, true, false)
		if n is Node3D:
			(n as Node3D).visible = false
	var players := scene.find_children("*", "AnimationPlayer", true, false)
	if players.is_empty():
		push_warning("Character: no AnimationPlayer in model; animations disabled.")
		return true
	anim = players[0]
	for clip in LOOPED_CLIPS:
		if anim.has_animation(clip):
			anim.get_animation(clip).loop_mode = Animation.LOOP_LINEAR
	_play("Idle")
	return true


func _play(clip: String, speed := 1.0) -> void:
	if anim == null or not anim.has_animation(clip):
		return
	if _current_clip != clip:
		anim.play(clip, BLEND_TIME)
		_current_clip = clip
	anim.speed_scale = speed


func _build_fallback_body() -> void:
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(0.55, 0.58, 0.62)
	m.metallic = 0.6
	m.roughness = 0.45
	var body := CapsuleMesh.new()
	body.radius = 0.3
	body.height = 1.7
	var mi := MeshInstance3D.new()
	mi.mesh = body
	mi.position = Vector3(0, 0.85, 0)
	mi.material_override = m
	rig.add_child(mi)


# ── camera ───────────────────────────────────────────────────────────────────

func _build_camera() -> void:
	# Over-the-shoulder cinematic follow camera.
	var gimbal := Node3D.new()
	gimbal.name = "Gimbal"
	gimbal.position = Vector3(0, 1.55, 0)
	add_child(gimbal)
	spring = SpringArm3D.new()
	spring.spring_length = 4.2
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
		cam_yaw -= mm.relative.x * LOOK_SPEED
		cam_pitch = clampf(cam_pitch - mm.relative.y * LOOK_SPEED, -1.2, 0.5)


func _physics_process(delta: float) -> void:
	if not camera.current:
		return

	# Camera gimbal.
	var gimbal := spring.get_parent() as Node3D
	gimbal.rotation = Vector3(cam_pitch, cam_yaw, 0)

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
		rig.rotation.y = lerp_angle(rig.rotation.y,
			atan2(wish.x, wish.z) + MODEL_YAW_OFFSET, TURN_LERP * delta)
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
	_update_animation(delta, jumped)


func _update_animation(delta: float, jumped: bool) -> void:
	if anim == null:
		return
	var airborne := not is_on_floor()
	var ground_speed := Vector2(velocity.x, velocity.z).length()

	if jumped:
		_play("Jump_Start")
	elif airborne:
		# Let Jump_Start finish before settling into the airborne loop.
		if _current_clip != "Jump_Start" or not anim.is_playing():
			_play("Jump_Idle")
	elif _was_airborne:
		_play("Jump_Land")
		_land_timer = 0.25
	elif _land_timer > 0.0:
		_land_timer -= delta
	elif ground_speed > RUN_SPEED * 0.65:
		# Match playback to actual speed so feet plant instead of sliding.
		_play("Running_B", clampf(ground_speed / RUN_SPEED, 0.7, 1.3))
	elif ground_speed > 0.25:
		_play("Walking_B", clampf(ground_speed / WALK_SPEED, 0.7, 1.4))
	else:
		_play("Idle")
	_was_airborne = airborne
