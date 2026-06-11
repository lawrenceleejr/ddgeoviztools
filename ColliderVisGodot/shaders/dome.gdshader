// Smooth, softly-lit studio dome enclosing the scene. Viewed from inside
// (cull_front); a gentle vertical gradient — deep below the horizon, a soft
// glow at eye level, calm zenith — so the detector floats in an even,
// photographic environment instead of a boxy hall.
shader_type spatial;
render_mode unshaded, cull_front;

uniform vec3 deep_color : source_color = vec3(0.008, 0.011, 0.018);
uniform vec3 horizon_color : source_color = vec3(0.050, 0.066, 0.092);
uniform vec3 zenith_color : source_color = vec3(0.016, 0.022, 0.036);

varying vec3 v_world_pos;

void vertex() {
	v_world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	float h = normalize(v_world_pos).y;   // -1 (below) .. 1 (above)
	vec3 col = mix(horizon_color, zenith_color, smoothstep(0.05, 0.75, h));
	col = mix(deep_color, col, smoothstep(-0.35, 0.05, h));
	ALBEDO = col;
}
