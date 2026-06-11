// Track tube with propagation reveal: each vertex carries its arc length
// from the interaction point in UV.x; fragments past the global reveal
// front (cv_event_reveal, metres — advanced at fixed speed by the event
// display) are discarded, so the trajectory draws on from the origin at
// constant speed. A short bright "head" pulses at the front while it moves.
shader_type spatial;

global uniform float cv_event_reveal;

uniform vec4 albedo : source_color = vec4(0.05, 0.05, 0.05, 1.0);
uniform vec4 emission_color : source_color = vec4(1.0, 0.5, 0.2, 1.0);
uniform float emission_energy = 2.0;

varying float v_arc;

void vertex() {
	v_arc = UV.x;
}

void fragment() {
	if (v_arc > cv_event_reveal) {
		discard;
	}
	ALBEDO = albedo.rgb;
	METALLIC = 0.0;
	ROUGHNESS = 0.4;
	// Brighten briefly just behind the moving front.
	float head = smoothstep(0.3, 0.0, cv_event_reveal - v_arc);
	EMISSION = emission_color.rgb * emission_energy * (1.0 + head * 1.6);
}
