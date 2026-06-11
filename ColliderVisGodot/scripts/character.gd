extends CharacterBody3D
## Third-person explorer: a stylized sci-fi mannequin (built procedurally —
## no asset files) with a procedural walk/run/idle animation cycle, driven
## à la UE's third-person template: WASD moves relative to the camera,
## Shift runs, Space jumps, the body turns toward the move direction.

const WALK_SPEED := 3.0
const RUN_SPEED := 6.5
const JUMP_VELOCITY := 4.8
const GRAVITY := 12.0
const TURN_LERP := 10.0
const LOOK_SPEED := 0.0035

var cam_yaw := 0.0
var cam_pitch := -0.18
var _phase := 0.0
var _speed_blend := 0.0   # 0 idle .. 1 run, smoothed

# Rig pivots.
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


func _ready() -> void:
	_build_body()
	_build_camera()
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.3
	capsule.height = 1.7
	shape.shape = capsule
	shape.position = Vector3(0, 0.85, 0)
	add_child(shape)


# ── procedural mannequin ─────────────────────────────────────────────────────

func _mat(color: Color, metallic := 0.6, roughness := 0.45,
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


func _part(parent: Node3D, mesh: Mesh, pos: Vector3, mat: Material) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.position = pos
	mi.material_override = mat
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


func _build_body() -> void:
	var suit := _mat(Color(0.55, 0.58, 0.62), 0.7, 0.4)
	var dark := _mat(Color(0.16, 0.17, 0.20), 0.3, 0.7)
	var accent := _mat(Color(0.1, 0.12, 0.15), 0.4, 0.5, Color(0.1, 0.7, 1.0), 3.0)

	rig = Node3D.new()
	add_child(rig)

	# Pelvis + torso + head (rig origin at feet).
	var pelvis := _pivot(rig, Vector3(0, 0.95, 0))
	_part(pelvis, _box(Vector3(0.32, 0.18, 0.22)), Vector3.ZERO, dark)
	torso = _pivot(pelvis, Vector3(0, 0.12, 0))
	_part(torso, _box(Vector3(0.38, 0.46, 0.24)), Vector3(0, 0.30, 0), suit)
	_part(torso, _box(Vector3(0.18, 0.10, 0.02)), Vector3(0, 0.38, 0.13), accent)  # chest light
	head = _pivot(torso, Vector3(0, 0.62, 0))
	var skull := SphereMesh.new()
	skull.radius = 0.13
	skull.height = 0.26
	_part(head, skull, Vector3(0, 0.10, 0), suit)
	_part(head, _box(Vector3(0.16, 0.05, 0.02)), Vector3(0, 0.11, 0.12), accent)   # visor

	# Arms.
	shoulder_l = _pivot(torso, Vector3(-0.26, 0.48, 0))
	shoulder_r = _pivot(torso, Vector3(0.26, 0.48, 0))
	for s in [shoulder_l, shoulder_r]:
		_part(s, _capsule(0.06, 0.34), Vector3(0, -0.16, 0), suit)
	elbow_l = _pivot(shoulder_l, Vector3(0, -0.34, 0))
	elbow_r = _pivot(shoulder_r, Vector3(0, -0.34, 0))
	for e in [elbow_l, elbow_r]:
		_part(e, _capsule(0.05, 0.32), Vector3(0, -0.15, 0), dark)

	# Legs.
	hip_l = _pivot(pelvis, Vector3(-0.10, -0.06, 0))
	hip_r = _pivot(pelvis, Vector3(0.10, -0.06, 0))
	for hp in [hip_l, hip_r]:
		_part(hp, _capsule(0.075, 0.42), Vector3(0, -0.21, 0), suit)
	knee_l = _pivot(hip_l, Vector3(0, -0.44, 0))
	knee_r = _pivot(hip_r, Vector3(0, -0.44, 0))
	for kn in [knee_l, knee_r]:
		_part(kn, _capsule(0.06, 0.40), Vector3(0, -0.20, 0), dark)
		_part(kn, _box(Vector3(0.11, 0.06, 0.24)), Vector3(0, -0.42, 0.05), dark)  # foot


func _build_camera() -> void:
	# Over-the-shoulder cinematic follow camera.
	var gimbal := Node3D.new()
	gimbal.name = "Gimbal"
	gimbal.position = Vector3(0, 1.55, 0)
	add_child(gimbal)
	spring = SpringArm3D.new()
	spring.spring_length = 3.4
	spring.collision_mask = 1
	gimbal.add_child(spring)
	camera = Camera3D.new()
	camera.fov = 65.0
	camera.near = 0.05
	camera.position = Vector3(0.45, 0.15, 0)   # slight shoulder offset
	var attrs := CameraAttributesPractical.new()
	attrs.dof_blur_far_enabled = true
	attrs.dof_blur_far_distance = 14.0
	attrs.dof_blur_far_transition = 10.0
	attrs.dof_blur_amount = 0.06
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
		rig.rotation.y = lerp_angle(rig.rotation.y, atan2(wish.x, wish.z), TURN_LERP * delta)
	else:
		velocity.x = move_toward(velocity.x, 0, speed * 4.0 * delta)
		velocity.z = move_toward(velocity.z, 0, speed * 4.0 * delta)

	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	elif Input.is_key_pressed(KEY_SPACE) and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		velocity.y = JUMP_VELOCITY

	move_and_slide()
	_animate(delta)


func _animate(delta: float) -> void:
	var ground_speed := Vector2(velocity.x, velocity.z).length()
	var target_blend := clampf(ground_speed / RUN_SPEED, 0.0, 1.0)
	_speed_blend = lerpf(_speed_blend, target_blend, 8.0 * delta)
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
	torso.position.y = 0.12 + bob + sin(_phase * 0.5) * 0.008 * (1.0 - k)
	torso.rotation.x = -0.12 * k
	head.rotation.x = 0.10 * k   # keep the visor level-ish while leaning
