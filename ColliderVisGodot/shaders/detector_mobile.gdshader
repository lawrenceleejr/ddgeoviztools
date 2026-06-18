// Mobile/Quest variant of the detector material.
//
// Same phi-cutaway and uniforms as detector.gdshader so detector_loader can
// drive it identically, but tuned for the Forward Mobile tiler:
//   - specular_disabled: the full PBR specular BRDF is the single most
//     expensive part of the per-fragment shading; the detector reads fine as
//     a matte surface under the flat ambient + fill rig used on mobile.
//   - diffuse_lambert: cheaper than the default Burley diffuse.
// cull_disabled is KEPT — the VTK-tessellated GDML meshes have inconsistent
// winding, so back-face culling would punch holes in the geometry.
shader_type spatial;
render_mode cull_disabled, specular_disabled, diffuse_lambert;

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
	if (!FRONT_FACING) {
		NORMAL = -NORMAL;
	}
	ALBEDO = albedo.rgb;
	METALLIC = metallic;
	ROUGHNESS = roughness;
}
