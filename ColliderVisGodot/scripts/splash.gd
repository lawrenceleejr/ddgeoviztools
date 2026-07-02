extends Control
## Splash screen: logo + title fade in over black, then hand off to the main
## scene. Any key/click skips. Headless/CI runs (--screenshot, --no-splash)
## skip straight to the visualizer so automation never waits on it.

const MAIN_SCENE := "res://scenes/main.tscn"

var _done := false


func _ready() -> void:
	# The splash is a 2D Control — it never reaches an HMD, so on the headset
	# it's just seconds of black before the world appears. Go straight in.
	if OS.has_feature("mobile"):
		_finish()
		return
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--screenshot") or arg == "--no-splash":
			_finish()
			return

	var bg := ColorRect.new()
	bg.color = Color(0.012, 0.016, 0.028)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var box := VBoxContainer.new()
	box.alignment = BoxContainer.ALIGNMENT_CENTER
	box.add_theme_constant_override("separation", 18)
	center.add_child(box)

	var logo := TextureRect.new()
	logo.texture = CVBranding.logo_texture(512)
	logo.custom_minimum_size = Vector2(256, 256)
	logo.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	logo.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	box.add_child(logo)

	var title := CVBranding.title_label(true)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(title)

	var sub := Label.new()
	sub.text = "Photo-realistic collision event display"
	sub.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	sub.add_theme_font_size_override("font_size", 16)
	sub.add_theme_color_override("font_color", Color(0.45, 0.58, 0.72))
	box.add_child(sub)

	# Fade in, hold, fade out, switch.
	modulate = Color(1, 1, 1, 0)
	var tw := create_tween()
	tw.tween_property(self, "modulate:a", 1.0, 0.7).set_trans(Tween.TRANS_SINE)
	tw.tween_interval(1.4)
	tw.tween_property(self, "modulate:a", 0.0, 0.5).set_trans(Tween.TRANS_SINE)
	tw.tween_callback(_finish)


func _input(event: InputEvent) -> void:
	if (event is InputEventKey or event is InputEventMouseButton) and event.pressed:
		_finish()


func _finish() -> void:
	if _done:
		return
	_done = true
	get_tree().change_scene_to_file.call_deferred(MAIN_SCENE)
