// Calorimeter hit cubes (MultiMesh). Per-instance COLOR carries the
// energy-lerped tint in rgb and the normalised energy in alpha; emission
// scales with energy so hot hits bloom.
shader_type spatial;

uniform float emission_scale = 7.0;

varying vec4 inst_color;

void vertex() {
	inst_color = COLOR;
}

void fragment() {
	ALBEDO = inst_color.rgb * 0.04;
	METALLIC = 0.0;
	ROUGHNESS = 0.6;
	EMISSION = inst_color.rgb * (0.4 + inst_color.a * emission_scale);
}
