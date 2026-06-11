// Calorimeter hit cubes (MultiMesh). Per-instance COLOR carries the
// energy-lerped tint in rgb and the normalised energy in alpha; emission
// scales with energy so hot hits bloom. Per-instance CUSTOM.r carries the
// hit's distance from the interaction point (metres): the hit only shows
// once the fixed-speed reveal front (cv_event_reveal) has reached it.
shader_type spatial;

global uniform float cv_event_reveal;

uniform float emission_scale = 7.0;

varying vec4 inst_color;
varying float v_dist;

void vertex() {
	inst_color = COLOR;
	v_dist = INSTANCE_CUSTOM.r;
}

void fragment() {
	if (v_dist > cv_event_reveal) {
		discard;
	}
	ALBEDO = inst_color.rgb * 0.04;
	METALLIC = 0.0;
	ROUGHNESS = 0.6;
	EMISSION = inst_color.rgb * (0.4 + inst_color.a * emission_scale);
}
