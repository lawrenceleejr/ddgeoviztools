// Detector PBR material with a global phi-cutaway.
//
// The cutaway discards fragments whose azimuthal angle (around the Z beam
// axis, phi = atan2(Y, X)) falls inside [cv_phi_min, cv_phi_max] degrees,
// revealing the detector interior — the same convention as the Blender
// pipeline's PhiCutaway geometry-nodes modifier.
//
// cull_disabled: VTK-tessellated GDML meshes have inconsistent winding, and
// the cutaway exposes interior back faces anyway.
shader_type spatial;
render_mode cull_disabled;

uniform vec4 albedo : source_color = vec4(0.6, 0.6, 0.6, 1.0);
uniform float metallic : hint_range(0.0, 1.0) = 0.7;
uniform float roughness : hint_range(0.0, 1.0) = 0.5;

global uniform float cv_phi_min;
global uniform float cv_phi_max;
global uniform float cv_cutaway_enabled;

varying vec3 v_world_pos;

void vertex() {
	v_world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	if (cv_cutaway_enabled > 0.5) {
		float phi = degrees(atan(v_world_pos.y, v_world_pos.x));
		if (phi >= cv_phi_min && phi <= cv_phi_max) {
			discard;
		}
	}
	// Light interior surfaces correctly.
	if (!FRONT_FACING) {
		NORMAL = -NORMAL;
	}
	// Clean, uniform surfaces — the soft GI does the talking.
	ALBEDO = albedo.rgb;
	METALLIC = metallic;
	ROUGHNESS = roughness;
	SPECULAR = 0.5;
}
