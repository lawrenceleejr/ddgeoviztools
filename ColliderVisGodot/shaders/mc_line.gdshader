// MC truth lines with the same propagation reveal as the track tubes:
// UV.x = distance from the interaction point (metres).
shader_type spatial;
render_mode cull_disabled;

global uniform float cv_event_reveal;

uniform vec4 line_color : source_color = vec4(0.45, 0.45, 0.95, 0.55);
uniform float emission_energy = 1.4;

varying float v_arc;

void vertex() {
	v_arc = UV.x;
}

void fragment() {
	if (v_arc > cv_event_reveal) {
		discard;
	}
	ALBEDO = vec3(0.0);
	EMISSION = line_color.rgb * emission_energy;
	ALPHA = line_color.a;
}
