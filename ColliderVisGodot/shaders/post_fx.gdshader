// Cinematic full-screen pass:
//   camera motion blur (directional, driven from script via `motion_vec`)
//   screen-space lens flare (ghosts + halo + anamorphic streak)
//   chromatic aberration, vignette, animated film grain
//
// DOF bokeh and volumetric god-rays are handled by the 3D pipeline
// (CameraAttributesPractical + volumetric fog); this pass adds the lens.
shader_type canvas_item;

uniform sampler2D screen_tex : hint_screen_texture, filter_linear;

uniform vec2 motion_vec = vec2(0.0);     // screen-space camera motion this frame
uniform float motion_blur_scale = 0.2;

uniform float flare_strength = 0.03;
uniform float flare_threshold = 0.90;    // post-tonemap luminance cut for flare sources

uniform float ca_strength = 0.45;        // chromatic aberration (px at corners)
uniform float vignette_intensity = 0.28;
uniform float vignette_softness = 2.2;
uniform float grain_amount = 0.004;

float hash12(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

// Bright-pass sample for flare ghosts: keeps only near-blown highlights.
vec3 bright(vec2 uv) {
	vec3 c = texture(screen_tex, clamp(uv, vec2(0.001), vec2(0.999))).rgb;
	float l = dot(c, vec3(0.299, 0.587, 0.114));
	return c * smoothstep(flare_threshold, 1.0, l);
}

void fragment() {
	vec2 uv = SCREEN_UV;
	vec2 centered = uv - 0.5;
	float r2 = dot(centered, centered);

	// ── Camera motion blur — 4 taps, skipped entirely when still ──
	vec2 mb = motion_vec * motion_blur_scale;
	mb = clamp(mb, vec2(-0.035), vec2(0.035));
	vec3 col;
	if (dot(mb, mb) > 1e-9) {
		col = vec3(0.0);
		const int MB_TAPS = 4;
		for (int i = 0; i < MB_TAPS; i++) {
			float t = (float(i) / float(MB_TAPS - 1)) - 0.5;
			col += texture(screen_tex, uv + mb * t).rgb;
		}
		col /= float(MB_TAPS);
	} else {
		col = texture(screen_tex, uv).rgb;
	}

	// ── Chromatic aberration — quadratic toward the edges ──
	vec2 px = ca_strength / vec2(textureSize(screen_tex, 0));
	vec2 shift = centered * r2 * 4.0 * px * 60.0;
	col.r = mix(col.r, texture(screen_tex, uv + shift).r, 0.85);
	col.b = mix(col.b, texture(screen_tex, uv - shift).b, 0.85);

	// ── Lens flare: ghosts + halo + anamorphic streak ──
	// Entire block skipped (uniform branch) when flares are disabled.
	if (flare_strength > 0.001) {
		vec3 flare = vec3(0.0);
		vec2 ghost_vec = (vec2(0.5) - uv) * 0.6;
		vec2 guv = uv;
		for (int i = 0; i < 3; i++) {
			guv += ghost_vec;
			float w = pow(1.0 - length(vec2(0.5) - guv) / 0.71, 4.0);
			flare += bright(guv) * max(w, 0.0) * 0.6;
		}
		// Halo ring on the opposite side of the lens centre.
		vec2 halo_uv = uv + normalize(ghost_vec + vec2(1e-5)) * 0.42;
		flare += bright(halo_uv) * pow(1.0 - abs(length(centered) - 0.35) * 4.0, 3.0) * 0.4;
		// Anamorphic horizontal streak from blown highlights.
		vec3 streak = vec3(0.0);
		for (int i = 1; i <= 3; i++) {
			float o = float(i) * float(i) * 0.011;
			streak += bright(uv + vec2(o, 0.0));
			streak += bright(uv - vec2(o, 0.0));
		}
		flare += streak * vec3(0.35, 0.55, 1.0) * 0.14;   // cool-blue streaks
		// Tint ghosts slightly toward the lens-coating purple/cyan.
		col += flare * flare_strength * vec3(0.85, 0.95, 1.15);
	}

	// ── Vignette ──
	float vig = 1.0 - vignette_intensity * pow(r2 * 2.0, vignette_softness * 0.5);
	col *= clamp(vig, 0.0, 1.0);

	// ── Animated film grain ──
	float g = (hash12(uv * vec2(1920.0, 1080.0) + fract(TIME) * 271.0) - 0.5) * grain_amount;
	col += g;

	COLOR = vec4(col, 1.0);
}
