extends CanvasLayer
## ColliderVis in-game UI:
##   - compact status strip (top-left)
##   - full menu panel (Esc / M): event file loading (JSON or EDM4HEP ROOT),
##     event index picker, event information (reco tracks + truth particles),
##     sub-detector visibility toggles, camera & cutaway controls
##   - file dialog + error dialog
##
## Built entirely in code — no editor assets needed.

var main: Node3D = null          # main.gd

var status: Label
var menu_root: Control
var file_dialog: FileDialog
var detector_dialog: FileDialog
var error_dialog: AcceptDialog
var event_info: RichTextLabel
var event_spin: SpinBox
var event_total: Label
var file_label: Label
var det_box: VBoxContainer
var det_checks: Dictionary = {}  # group name -> CheckBox
var phi_slider: HSlider
var cutaway_check: CheckBox
var mode_label: Label
var fps_label: Label
var _fps_accum := 0.0

const PANEL_W := 560.0
const FONT_SIZE := 16
const HEADER_SIZE := 19

## Post-FX defaults (restored when an effect checkbox is re-enabled).
const FX_DEFAULTS := {
	"flare_strength": 0.10,
	"motion_blur_scale": 0.7,
	"ca_strength": 0.45,
	"grain_amount": 0.008,
	"vignette_intensity": 0.28,
}


func build(p_main: Node3D) -> void:
	main = p_main
	layer = 20
	_build_status()
	_build_menu()
	_build_dialogs()
	refresh()


# ── status strip ─────────────────────────────────────────────────────────────

func _build_status() -> void:
	status = Label.new()
	status.position = Vector2(16, 12)
	status.add_theme_font_size_override("font_size", FONT_SIZE)
	status.add_theme_color_override("font_color", Color(0.8, 0.9, 1.0, 0.85))
	status.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.9))
	status.add_theme_constant_override("shadow_offset_x", 1)
	status.add_theme_constant_override("shadow_offset_y", 1)
	add_child(status)


# ── menu panel ───────────────────────────────────────────────────────────────

func _section(parent: Control, title: String) -> VBoxContainer:
	var lbl := Label.new()
	lbl.text = title
	lbl.add_theme_font_size_override("font_size", HEADER_SIZE)
	lbl.add_theme_color_override("font_color", Color(0.55, 0.75, 0.95))
	parent.add_child(lbl)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	parent.add_child(box)
	var sep := HSeparator.new()
	parent.add_child(sep)
	return box


func _check(text: String, pressed: bool, cb: Callable) -> CheckBox:
	var c := CheckBox.new()
	c.text = text
	c.focus_mode = Control.FOCUS_NONE
	c.set_pressed_no_signal(pressed)
	c.toggled.connect(cb)
	return c


func _labeled_slider(parent: Control, text: String, minv: float, maxv: float,
		step: float, value: float, cb: Callable) -> HSlider:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	var l := Label.new()
	l.text = text
	l.custom_minimum_size = Vector2(150, 0)
	row.add_child(l)
	var s := HSlider.new()
	s.min_value = minv
	s.max_value = maxv
	s.step = step
	s.value = value
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.focus_mode = Control.FOCUS_NONE
	s.value_changed.connect(cb)
	row.add_child(s)
	parent.add_child(row)
	return s


func _button(text: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.focus_mode = Control.FOCUS_NONE   # keep Space free for next-event/jump
	b.pressed.connect(cb)
	return b


func _build_menu() -> void:
	menu_root = PanelContainer.new()
	menu_root.visible = false
	menu_root.anchor_left = 1.0
	menu_root.anchor_right = 1.0
	menu_root.anchor_bottom = 1.0
	menu_root.offset_left = -PANEL_W
	menu_root.offset_right = 0
	menu_root.offset_top = 0
	menu_root.offset_bottom = 0
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.03, 0.05, 0.09, 0.92)
	style.border_color = Color(0.15, 0.30, 0.45)
	style.border_width_left = 2
	style.content_margin_left = 14
	style.content_margin_right = 14
	style.content_margin_top = 10
	style.content_margin_bottom = 10
	menu_root.add_theme_stylebox_override("panel", style)
	# One theme bump makes every control in the panel comfortably large.
	var theme := Theme.new()
	theme.default_font_size = FONT_SIZE
	menu_root.theme = theme
	add_child(menu_root)

	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	menu_root.add_child(scroll)

	var col := VBoxContainer.new()
	col.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	col.add_theme_constant_override("separation", 8)
	scroll.add_child(col)

	# Header: logo + name.
	var head := HBoxContainer.new()
	head.add_theme_constant_override("separation", 12)
	var logo := TextureRect.new()
	logo.texture = CVBranding.logo_texture(128)
	logo.custom_minimum_size = Vector2(56, 56)
	logo.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	logo.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	head.add_child(logo)
	var head_col := VBoxContainer.new()
	head_col.add_child(CVBranding.title_label(false))
	var tag := Label.new()
	tag.text = "collision event display"
	tag.add_theme_font_size_override("font_size", 12)
	tag.add_theme_color_override("font_color", Color(0.45, 0.58, 0.72))
	head_col.add_child(tag)
	head.add_child(head_col)
	col.add_child(head)
	col.add_child(HSeparator.new())

	# ── Events ──
	var ev := _section(col, "EVENTS")
	file_label = Label.new()
	file_label.text = "(no file loaded)"
	file_label.add_theme_font_size_override("font_size", 12)
	file_label.clip_text = true
	file_label.custom_minimum_size = Vector2(PANEL_W - 40, 0)
	ev.add_child(file_label)
	ev.add_child(_button("Open event file…  (.json / .root)", _on_open_file))

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	row.add_child(_button("◀ Prev", func(): main.show_relative_event(-1)))
	event_spin = SpinBox.new()
	event_spin.min_value = 0
	event_spin.step = 1
	event_spin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	event_spin.value_changed.connect(func(v: float): main.show_event_index(int(v)))
	row.add_child(event_spin)
	event_total = Label.new()
	event_total.text = "/ 0"
	row.add_child(event_total)
	row.add_child(_button("Next ▶  (Space)", func(): main.show_relative_event(1)))
	ev.add_child(row)

	# ── Event info ──
	var info := _section(col, "EVENT INFORMATION")
	event_info = RichTextLabel.new()
	event_info.bbcode_enabled = true
	event_info.fit_content = false
	event_info.custom_minimum_size = Vector2(0, 280)
	event_info.size_flags_vertical = Control.SIZE_EXPAND_FILL
	event_info.add_theme_font_size_override("normal_font_size", 14)
	event_info.add_theme_font_size_override("mono_font_size", 14)
	info.add_child(event_info)
	var ev_toggle := _check("Show event display", true,
		func(on: bool): main.set_event_display_visible(on))
	info.add_child(ev_toggle)

	# ── Detector ──
	var det := _section(col, "DETECTOR")
	det.add_child(_button("Load detector folder…  (.gltf per sub-detector)",
		_on_open_detector))
	var det_row := HBoxContainer.new()
	det_row.add_theme_constant_override("separation", 6)
	det_row.add_child(_button("Show all", func(): main.set_all_groups(true)))
	det_row.add_child(_button("Hide all", func(): main.set_all_groups(false)))
	det.add_child(det_row)
	det_box = VBoxContainer.new()
	det.add_child(det_box)

	# ── Camera & cutaway ──
	var cam := _section(col, "CAMERA & CUTAWAY")
	mode_label = Label.new()
	mode_label.add_theme_font_size_override("font_size", 13)
	cam.add_child(mode_label)
	cam.add_child(_button("Cycle camera mode  (Tab)", func(): main.cycle_camera_mode()))
	cutaway_check = CheckBox.new()
	cutaway_check.text = "Phi cutaway (C)"
	cutaway_check.focus_mode = Control.FOCUS_NONE
	cutaway_check.toggled.connect(func(on: bool): main.set_cutaway(on))
	cam.add_child(cutaway_check)
	var slider_row := HBoxContainer.new()
	var sl := Label.new()
	sl.text = "Opening"
	slider_row.add_child(sl)
	phi_slider = HSlider.new()
	phi_slider.min_value = 0
	phi_slider.max_value = 360
	phi_slider.step = 5
	phi_slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	phi_slider.focus_mode = Control.FOCUS_NONE
	phi_slider.value_changed.connect(func(v: float): main.set_phi_max(v))
	slider_row.add_child(phi_slider)
	cam.add_child(slider_row)

	# ── Settings ──
	var s := _section(col, "SETTINGS")

	fps_label = Label.new()
	fps_label.add_theme_color_override("font_color", Color(0.65, 0.95, 0.7))
	s.add_child(fps_label)
	var gpu := Label.new()
	gpu.text = "GPU: %s  ·  driver: %s" % [RenderingServer.get_video_adapter_name(),
		RenderingServer.get_current_rendering_driver_name()]
	gpu.add_theme_font_size_override("font_size", 13)
	gpu.add_theme_color_override("font_color", Color(0.5, 0.6, 0.7))
	s.add_child(gpu)

	# Window resolution + fullscreen.
	var res_row := HBoxContainer.new()
	res_row.add_theme_constant_override("separation", 8)
	var res_lbl := Label.new()
	res_lbl.text = "Resolution"
	res_lbl.custom_minimum_size = Vector2(150, 0)
	res_row.add_child(res_lbl)
	var res_opt := OptionButton.new()
	res_opt.focus_mode = Control.FOCUS_NONE
	for r in main.RESOLUTIONS:
		res_opt.add_item("%d × %d" % [r.x, r.y])
	var cur := DisplayServer.window_get_size()
	for i in main.RESOLUTIONS.size():
		if main.RESOLUTIONS[i] == cur:
			res_opt.select(i)
	res_opt.item_selected.connect(func(i: int): main.set_resolution_index(i))
	res_opt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	res_row.add_child(res_opt)
	s.add_child(res_row)
	s.add_child(_check("Fullscreen", false, func(on: bool): main.set_fullscreen(on)))

	# Render quality.
	var q_row := HBoxContainer.new()
	q_row.add_theme_constant_override("separation", 8)
	var q_lbl := Label.new()
	q_lbl.text = "Quality preset"
	q_lbl.custom_minimum_size = Vector2(150, 0)
	q_row.add_child(q_lbl)
	var q_opt := OptionButton.new()
	q_opt.focus_mode = Control.FOCUS_NONE
	for q in ["Performance", "Balanced", "Quality"]:
		q_opt.add_item(q)
	q_opt.select(1)
	q_opt.item_selected.connect(
		func(i: int): main.apply_quality(["performance", "balanced", "quality"][i]))
	q_opt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	q_row.add_child(q_opt)
	s.add_child(q_row)

	_labeled_slider(s, "Render scale", 0.5, 1.0, 0.05, 1.0,
		func(v: float): main.set_render_scale(v))
	_labeled_slider(s, "Light brightness", 0.4, 1.6, 0.05, main.light_scale,
		func(v: float): main.set_light_scale(v))
	_labeled_slider(s, "Depth of field", 0.0, 0.3, 0.01, 0.07,
		func(v: float): main.set_dof_amount(v))

	# Lens / camera effects.
	for fx in [["Lens flares", "flare_strength"],
			["Motion blur", "motion_blur_scale"],
			["Chromatic aberration", "ca_strength"],
			["Film grain", "grain_amount"],
			["Vignette", "vignette_intensity"]]:
		var param: String = fx[1]
		var cb := func(on: bool): main.set_fx_param(param, FX_DEFAULTS[param] if on else 0.0)
		s.add_child(_check(String(fx[0]), true, cb))

	# ── Help ──
	var help := _section(col, "CONTROLS")
	var h := Label.new()
	h.add_theme_font_size_override("font_size", 14)
	h.add_theme_color_override("font_color", Color(0.6, 0.7, 0.8))
	h.text = ("Esc — menu + cursor · mouse drives the camera otherwise\n"
		+ "Hold RMB — smooth zoom to examine details\n"
		+ "Orbit: mouse orbits · wheel distance · MMB pan\n"
		+ "Fly: WASD + QE · Shift fast · mouse look\n"
		+ "Walk: WASD · Shift run · Space jump\n"
		+ "Space next event · B previous event\n"
		+ "1–9 toggle sub-detectors · 0 show all\n"
		+ "C cutaway · [ ] opening · H HUD")
	help.add_child(h)

	# ── Credits ──
	var cred := _section(col, "CREDITS")
	var c := RichTextLabel.new()
	c.bbcode_enabled = true
	c.fit_content = true
	c.add_theme_font_size_override("normal_font_size", 13)
	c.text = ("Character: [url=https://github.com/gdquest-demos/godot-3d-mannequin]"
		+ "\"Mannequiny\"[/url] by [url=https://www.gdquest.com/]GDQuest and "
		+ "contributors[/url] — licensed [url=https://creativecommons.org/"
		+ "licenses/by/4.0/]CC-BY 4.0[/url]\n"
		+ "Built with [url=https://godotengine.org]Godot Engine[/url]\n"
		+ "Geometry pipeline: ddgeoviztools (DD4hep/ddsim → glTF)\n"
		+ "Event model: EDM4HEP / key4hep")
	c.meta_clicked.connect(func(meta): OS.shell_open(str(meta)))
	cred.add_child(c)


# ── dialogs ──────────────────────────────────────────────────────────────────

func _build_dialogs() -> void:
	file_dialog = FileDialog.new()
	file_dialog.access = FileDialog.ACCESS_FILESYSTEM
	file_dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	file_dialog.use_native_dialog = true   # system file picker
	file_dialog.filters = PackedStringArray([
		"*.json ; Converted event JSON",
		"*.root ; EDM4HEP / key4hep ROOT file"])
	file_dialog.size = Vector2(900, 600)
	file_dialog.file_selected.connect(_on_file_selected)
	add_child(file_dialog)

	detector_dialog = FileDialog.new()
	detector_dialog.access = FileDialog.ACCESS_FILESYSTEM
	detector_dialog.file_mode = FileDialog.FILE_MODE_OPEN_DIR
	detector_dialog.use_native_dialog = true
	detector_dialog.title = "Pick a folder of sub-detector .gltf files"
	detector_dialog.size = Vector2(900, 600)
	detector_dialog.dir_selected.connect(func(dir: String): main.load_detector_dir(dir))
	add_child(detector_dialog)

	error_dialog = AcceptDialog.new()
	error_dialog.title = "ColliderVis"
	add_child(error_dialog)


func _on_open_file() -> void:
	file_dialog.popup_centered()


func _on_open_detector() -> void:
	detector_dialog.popup_centered()


## Called when the detector group set changes (new geometry loaded).
func reset_detector_list() -> void:
	for child in det_box.get_children():
		child.queue_free()
	det_checks.clear()
	refresh()


func _on_file_selected(path: String) -> void:
	main.open_event_path(path)


func show_error(msg: String) -> void:
	error_dialog.dialog_text = msg
	error_dialog.popup_centered()


# ── state refresh ────────────────────────────────────────────────────────────

func _process(delta: float) -> void:
	if not menu_root.visible or fps_label == null:
		return
	_fps_accum -= delta
	if _fps_accum <= 0.0:
		_fps_accum = 0.4
		fps_label.text = "FPS: %d" % Engine.get_frames_per_second()


func toggle_menu() -> void:
	# Mouse capture policy lives in main._sync_mouse_mode().
	menu_root.visible = not menu_root.visible
	if menu_root.visible:
		refresh()


func is_menu_open() -> bool:
	return menu_root.visible


func refresh() -> void:
	if main == null:
		return
	# Status strip.
	var lines := []
	if main.event_index >= 0 and not main.event_files.is_empty():
		lines.append("Event %d / %d — %s" % [main.event_index + 1,
			main.event_files.size(),
			String(main.event_files[main.event_index]).get_file()])
	lines.append("%s · Esc menu · Tab camera · Space next event"
		% main.camera_mode_name())
	status.text = "\n".join(lines)

	# Events section.
	var n: int = main.event_files.size()
	event_total.text = "/ %d" % n
	event_spin.max_value = maxf(0, n - 1)
	event_spin.set_value_no_signal(maxi(0, main.event_index))
	if main.event_index >= 0 and n > 0:
		file_label.text = String(main.event_files[main.event_index])
		file_label.tooltip_text = file_label.text
	event_info.text = main.event_summary_bbcode()

	# Detector toggles.
	for g in main.group_order:
		if not det_checks.has(g):
			var cb := CheckBox.new()
			cb.text = str(g)
			cb.focus_mode = Control.FOCUS_NONE
			cb.toggled.connect(func(on: bool): main.set_group_visible(g, on))
			det_box.add_child(cb)
			det_checks[g] = cb
	for g in det_checks:
		var nodes: Array = main.detector_groups.get(g, [])
		if not nodes.is_empty():
			(det_checks[g] as CheckBox).set_pressed_no_signal(
				(nodes[0] as Node3D).visible)

	# Camera & cutaway.
	mode_label.text = "Mode: %s" % main.camera_mode_name()
	cutaway_check.set_pressed_no_signal(main.cutaway_enabled)
	phi_slider.set_value_no_signal(main.phi_max)
