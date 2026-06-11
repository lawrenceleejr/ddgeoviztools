extends Camera3D
## Cinematic orbit / fly camera.
##
##   Orbit (default): LMB-drag orbits the detector, wheel zooms, MMB pans.
##                    All motion is inertia-smoothed; after a few idle
##                    seconds the camera drifts into a slow auto-orbit.
##   Fly:             mouse-look with WASD + Q/E vertical, Shift = fast.
##
## Mode switching (Tab) and menu/Esc handling live in main.gd.
## Depth-of-field bokeh tracks the orbit distance automatically.

var target := Vector3.ZERO
var distance := 13.5
var yaw := deg_to_rad(38.0)
var pitch := deg_to_rad(22.0)
var fly_mode := false

# Smoothed (rendered) state — follows the targets above with inertia.
var _s_yaw := deg_to_rad(38.0)
var _s_pitch := deg_to_rad(22.0)
var _s_distance := 13.5
var _s_target := Vector3.ZERO

var _dragging := false
var _idle_time := 0.0
var _attrs: CameraAttributesPractical

const MIN_DISTANCE := 1.0
const MAX_DISTANCE := 40.0
const ORBIT_SPEED := 0.008
const FLY_LOOK_SPEED := 0.0035
const FLY_SPEED := 6.0
const SMOOTHING := 9.0
const AUTO_ORBIT_DELAY := 5.0
const AUTO_ORBIT_RATE := 0.05    # rad/s, slow cinematic drift


func _ready() -> void:
	fov = 60.0
	near = 0.05
	far = 200.0
	_attrs = CameraAttributesPractical.new()
	_attrs.dof_blur_far_enabled = true
	_attrs.dof_blur_amount = 0.07
	attributes = _attrs
	_apply_orbit(true)


func set_fly(enabled: bool) -> void:
	if fly_mode == enabled:
		return
	fly_mode = enabled
	if enabled:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	else:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		# Re-derive orbit parameters from the current pose.
		var offset := position - target
		distance = clampf(offset.length(), MIN_DISTANCE, MAX_DISTANCE)
		pitch = asin(clampf(offset.y / maxf(offset.length(), 1e-6), -0.99, 0.99))
		yaw = atan2(offset.z, offset.x)
		_s_yaw = yaw
		_s_pitch = pitch
		_s_distance = distance
		_apply_orbit(true)


func _apply_orbit(snap := false) -> void:
	if snap:
		_s_yaw = yaw
		_s_pitch = pitch
		_s_distance = distance
		_s_target = target
	var dir := Vector3(
		cos(_s_pitch) * cos(_s_yaw),
		sin(_s_pitch),
		cos(_s_pitch) * sin(_s_yaw))
	position = _s_target + dir * _s_distance
	look_at(_s_target, Vector3.UP)


func _unhandled_input(event: InputEvent) -> void:
	if not current:
		return
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if fly_mode:
			return
		match mb.button_index:
			MOUSE_BUTTON_LEFT:
				_dragging = mb.pressed
				_idle_time = 0.0
			MOUSE_BUTTON_WHEEL_UP:
				distance = clampf(distance * 0.90, MIN_DISTANCE, MAX_DISTANCE)
				_idle_time = 0.0
			MOUSE_BUTTON_WHEEL_DOWN:
				distance = clampf(distance / 0.90, MIN_DISTANCE, MAX_DISTANCE)
				_idle_time = 0.0
		return

	if event is InputEventMouseMotion:
		var mm := event as InputEventMouseMotion
		if fly_mode and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
			rotate_y(-mm.relative.x * FLY_LOOK_SPEED)
			rotate_object_local(Vector3.RIGHT, -mm.relative.y * FLY_LOOK_SPEED)
			_idle_time = 0.0
		elif _dragging:
			yaw += mm.relative.x * ORBIT_SPEED
			pitch = clampf(pitch + mm.relative.y * ORBIT_SPEED,
				deg_to_rad(-85.0), deg_to_rad(85.0))
			_idle_time = 0.0
		elif Input.is_mouse_button_pressed(MOUSE_BUTTON_MIDDLE):
			var r := global_transform.basis.x
			var u := global_transform.basis.y
			target += (-r * mm.relative.x + u * mm.relative.y) * distance * 0.0015
			_idle_time = 0.0


func _process(delta: float) -> void:
	if not current:
		return
	if fly_mode:
		var dir := Vector3.ZERO
		if Input.is_key_pressed(KEY_W): dir -= global_transform.basis.z
		if Input.is_key_pressed(KEY_S): dir += global_transform.basis.z
		if Input.is_key_pressed(KEY_A): dir -= global_transform.basis.x
		if Input.is_key_pressed(KEY_D): dir += global_transform.basis.x
		if Input.is_key_pressed(KEY_Q): dir -= Vector3.UP
		if Input.is_key_pressed(KEY_E): dir += Vector3.UP
		if dir.length() > 0.01:
			var speed := FLY_SPEED * (3.0 if Input.is_key_pressed(KEY_SHIFT) else 1.0)
			position += dir.normalized() * speed * delta
			_idle_time = 0.0
		# DOF: focus mid-field while flying.
		_attrs.dof_blur_far_distance = 16.0
		_attrs.dof_blur_far_transition = 12.0
		return

	# Idle auto-orbit — slow cinematic turntable drift.
	_idle_time += delta
	if _idle_time > AUTO_ORBIT_DELAY:
		yaw += AUTO_ORBIT_RATE * delta * minf((_idle_time - AUTO_ORBIT_DELAY) / 3.0, 1.0)

	# Inertia smoothing.
	var k := 1.0 - exp(-SMOOTHING * delta)
	_s_yaw = lerpf(_s_yaw, yaw, k)
	_s_pitch = lerpf(_s_pitch, pitch, k)
	_s_distance = lerpf(_s_distance, distance, k)
	_s_target = _s_target.lerp(target, k)
	_apply_orbit()

	# DOF bokeh tracks the subject: focus starts past the orbit target so
	# the detector stays crisp while the dome melts away.
	_attrs.dof_blur_far_distance = _s_distance * 1.45
	_attrs.dof_blur_far_transition = _s_distance * 1.1
