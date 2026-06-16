extends Node3D
## World-space VR menu: a 2D Control rendered into a SubViewport, shown on a
## quad floating in front of the player, driven by a laser pointer from the
## right controller (2D overlays/CanvasLayers don't render to an HMD, so the
## desktop menu is unreachable in VR — this is its in-headset equivalent).
##
## main.gd drives it: open(head_xform) / close(), point(world_hit) each frame
## from the controller raycast, and click(pressed) on the trigger.

const VP_W := 760
const VP_H := 1040
const QUAD_W := 0.76
const QUAD_H := 1.04

var main: Node3D
var sub_vp: SubViewport
var quad: MeshInstance3D
var body: StaticBody3D
var _root: Control
var _light_slider: HSlider
var _scale_slider: HSlider
var _det_box: VBoxContainer
var _det_checks: Dictionary = {}
var _mouse_in := false
var _last_uv := Vector2.ZERO


func setup(p_main: Node3D) -> void:
	main = p_main
	visible = false

	sub_vp = SubViewport.new()
	sub_vp.size = Vector2i(VP_W, VP_H)
	sub_vp.transparent_bg = true
	sub_vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	sub_vp.gui_embed_subwindows = false
	add_child(sub_vp)
	_build_ui()

	quad = MeshInstance3D.new()
	var qm := QuadMesh.new()
	qm.size = Vector2(QUAD_W, QUAD_H)
	quad.mesh = qm
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_texture = sub_vp.get_texture()
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mat.no_depth_test = false
	quad.material_override = mat
	quad.gi_mode = GeometryInstance3D.GI_MODE_DISABLED
	add_child(quad)

	body = StaticBody3D.new()
	body.collision_layer = 1 << 4   # dedicated "VR UI" layer; laser only hits this
	body.collision_mask = 0
	var col := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(QUAD_W, QUAD_H, 0.04)
	col.shape = box
	body.add_child(col)
	add_child(body)


func is_open() -> bool:
	return visible


func toggle(head_xform: Transform3D) -> void:
	if visible:
		close()
	else:
		open(head_xform)


func open(head_xform: Transform3D) -> void:
	# Float the panel ~1.4 m in front of the head, at eye height, facing
	# the user (quad's textured +Z face turned toward them).
	var fwd := -head_xform.basis.z
	fwd.y = 0.0
	if fwd.length() < 1e-3:
		fwd = Vector3.FORWARD
	fwd = fwd.normalized()
	var pos := head_xform.origin + fwd * 1.4
	pos.y = head_xform.origin.y - 0.1
	look_at_from_position(pos, head_xform.origin, Vector3.UP)
	rotate_object_local(Vector3.UP, PI)   # show the +Z (un-mirrored) face
	_refresh()
	visible = true


func close() -> void:
	visible = false


## Map a world-space ray hit on the panel to a SubViewport mouse-move.
## Returns true if the hit lands on the panel.
func point(world_hit: Vector3) -> bool:
	var local := quad.to_local(world_hit)
	var u := local.x / QUAD_W + 0.5
	var v := 0.5 - local.y / QUAD_H
	if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
		if _mouse_in:
			_mouse_in = false
		return false
	_mouse_in = true
	_last_uv = Vector2(u * VP_W, v * VP_H)
	var ev := InputEventMouseMotion.new()
	ev.position = _last_uv
	sub_vp.push_input(ev)
	return true


func click(pressed: bool) -> void:
	if not _mouse_in:
		return
	var ev := InputEventMouseButton.new()
	ev.button_index = MOUSE_BUTTON_LEFT
	ev.pressed = pressed
	ev.position = _last_uv
	sub_vp.push_input(ev)


# ── UI ───────────────────────────────────────────────────────────────────────

func _btn(text: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(0, 64)
	b.add_theme_font_size_override("font_size", 30)
	b.pressed.connect(cb)
	return b


func _build_ui() -> void:
	_root = Control.new()
	_root.size = Vector2(VP_W, VP_H)
	sub_vp.add_child(_root)

	var bg := ColorRect.new()
	bg.color = Color(0.03, 0.05, 0.09, 0.93)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.add_child(bg)

	var pad := MarginContainer.new()
	pad.set_anchors_preset(Control.PRESET_FULL_RECT)
	for m in ["margin_left", "margin_right", "margin_top", "margin_bottom"]:
		pad.add_theme_constant_override(m, 28)
	_root.add_child(pad)

	var col := VBoxContainer.new()
	col.add_theme_constant_override("separation", 14)
	pad.add_child(col)

	var title := Label.new()
	title.text = "ColliderVis — VR"
	title.add_theme_font_size_override("font_size", 40)
	title.add_theme_color_override("font_color", Color(0.88, 0.95, 1.0))
	col.add_child(title)

	var ev := HBoxContainer.new()
	ev.add_theme_constant_override("separation", 14)
	var prev := _btn("◀ Prev", _on_prev)
	prev.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var nxt := _btn("Next ▶", _on_next)
	nxt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	ev.add_child(prev)
	ev.add_child(nxt)
	col.add_child(ev)

	col.add_child(_btn("Toggle event display", _on_toggle_events))
	col.add_child(_btn("Passthrough (mixed reality)", _on_passthrough))

	var cut := HBoxContainer.new()
	cut.add_theme_constant_override("separation", 14)
	var ctog := _btn("Cutaway on/off", _on_cutaway)
	ctog.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	cut.add_child(ctog)
	cut.add_child(_btn("–", _on_phi_minus))
	cut.add_child(_btn("+", _on_phi_plus))
	col.add_child(cut)

	col.add_child(_slider_row("Brightness", 0.4, 1.6, 0.05, main.light_scale, _on_light))
	col.add_child(_slider_row("Render scale", 0.5, 1.0, 0.05,
		main.get_viewport().scaling_3d_scale, _on_scale))

	var det_lbl := Label.new()
	det_lbl.text = "Sub-detectors"
	det_lbl.add_theme_font_size_override("font_size", 28)
	det_lbl.add_theme_color_override("font_color", Color(0.55, 0.75, 0.95))
	col.add_child(det_lbl)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.custom_minimum_size = Vector2(0, 300)
	col.add_child(scroll)
	_det_box = VBoxContainer.new()
	_det_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(_det_box)

	var foot := HBoxContainer.new()
	foot.add_theme_constant_override("separation", 14)
	var recenter := _btn("Recenter", _on_recenter)
	recenter.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var close_b := _btn("Close", _on_close)
	close_b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	foot.add_child(recenter)
	foot.add_child(close_b)
	col.add_child(foot)


func _slider_row(label: String, lo: float, hi: float, step: float,
		value: float, cb: Callable) -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)
	var l := Label.new()
	l.text = label
	l.custom_minimum_size = Vector2(220, 0)
	l.add_theme_font_size_override("font_size", 28)
	row.add_child(l)
	var s := HSlider.new()
	s.min_value = lo
	s.max_value = hi
	s.step = step
	s.value = value
	s.custom_minimum_size = Vector2(0, 56)
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.value_changed.connect(cb)
	row.add_child(s)
	if label == "Brightness":
		_light_slider = s
	else:
		_scale_slider = s
	return row


func _refresh() -> void:
	# Rebuild the sub-detector toggle list from the current geometry.
	for c in _det_box.get_children():
		c.queue_free()
	_det_checks.clear()
	for g in main.group_order:
		var cb := CheckBox.new()
		cb.text = str(g)
		cb.add_theme_font_size_override("font_size", 28)
		var nodes: Array = main.detector_groups.get(g, [])
		if not nodes.is_empty():
			cb.set_pressed_no_signal((nodes[0] as Node3D).visible)
		cb.toggled.connect(_on_det_toggle.bind(g))
		_det_box.add_child(cb)
		_det_checks[g] = cb
	if _light_slider:
		_light_slider.set_value_no_signal(main.light_scale)
	if _scale_slider:
		_scale_slider.set_value_no_signal(main.get_viewport().scaling_3d_scale)


# ── button handlers ──────────────────────────────────────────────────────────

func _on_prev() -> void: main.show_relative_event(-1)
func _on_next() -> void: main.show_relative_event(1)
func _on_toggle_events() -> void: main.set_event_display_visible(not main.show_events)
func _on_passthrough() -> void: main.set_passthrough(not main.passthrough_on)
func _on_cutaway() -> void: main.set_cutaway(not main.cutaway_enabled)
func _on_phi_minus() -> void: main.set_phi_max(main.phi_max - 15.0)
func _on_phi_plus() -> void: main.set_phi_max(main.phi_max + 15.0)
func _on_light(v: float) -> void: main.set_light_scale(v)
func _on_scale(v: float) -> void: main.set_render_scale(v)
func _on_recenter() -> void: main.xr_recenter()
func _on_close() -> void: close()
func _on_det_toggle(pressed: bool, group: String) -> void:
	main.set_group_visible(group, pressed)
