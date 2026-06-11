extends RefCounted
class_name CVBranding
## ColliderVis logo, generated at runtime from inline SVG so no imported
## texture assets are required. The mark is a detector cross-section
## (tracker / ECal / HCal rings) with charged-particle tracks curving out
## of the interaction point.

const ACCENT_CYAN := Color(0.1, 0.7, 1.0)
const ACCENT_ORANGE := Color(1.0, 0.4, 0.1)

const LOGO_SVG := """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <radialGradient id="bg" cx="50%" cy="45%" r="60%">
      <stop offset="0%" stop-color="#101826"/>
      <stop offset="100%" stop-color="#05080f"/>
    </radialGradient>
  </defs>
  <circle cx="128" cy="128" r="124" fill="url(#bg)" stroke="#27384f" stroke-width="3"/>
  <!-- HCal ring -->
  <circle cx="128" cy="128" r="100" fill="none" stroke="#8a6234" stroke-width="14" opacity="0.95"/>
  <!-- ECal ring -->
  <circle cx="128" cy="128" r="74" fill="none" stroke="#4d9e85" stroke-width="9" opacity="0.95"/>
  <!-- solenoid -->
  <circle cx="128" cy="128" r="58" fill="none" stroke="#b56a39" stroke-width="4" opacity="0.9"/>
  <!-- tracker -->
  <circle cx="128" cy="128" r="44" fill="none" stroke="#3b6ea8" stroke-width="3" opacity="0.85"/>
  <circle cx="128" cy="128" r="33" fill="none" stroke="#3b6ea8" stroke-width="2" opacity="0.6"/>
  <!-- positive tracks (warm) -->
  <path d="M128,128 q34,-12 52,-46" fill="none" stroke="#ff6619" stroke-width="5" stroke-linecap="round"/>
  <path d="M128,128 q10,38 -16,66" fill="none" stroke="#ff6619" stroke-width="4" stroke-linecap="round"/>
  <!-- negative tracks (cool) -->
  <path d="M128,128 q-36,-8 -58,-34" fill="none" stroke="#1ab2ff" stroke-width="5" stroke-linecap="round"/>
  <path d="M128,128 q-6,40 24,62" fill="none" stroke="#1ab2ff" stroke-width="4" stroke-linecap="round"/>
  <!-- neutral -->
  <path d="M128,128 L172,150" fill="none" stroke="#e8f2ff" stroke-width="3"
        stroke-linecap="round" stroke-dasharray="7,6"/>
  <!-- interaction point -->
  <circle cx="128" cy="128" r="9" fill="#fff3da"/>
  <circle cx="128" cy="128" r="16" fill="none" stroke="#ffd9a0" stroke-width="2" opacity="0.55"/>
</svg>
"""


static func logo_texture(size_px: int = 256) -> ImageTexture:
	var img := Image.new()
	var err := img.load_svg_from_string(LOGO_SVG, float(size_px) / 256.0)
	if err != OK:
		# Fallback: flat placeholder so UI never breaks.
		img = Image.create(size_px, size_px, false, Image.FORMAT_RGBA8)
		img.fill(Color(0.06, 0.09, 0.14))
	return ImageTexture.create_from_image(img)


static func title_label(big: bool = true) -> Label:
	var l := Label.new()
	l.text = "ColliderVis"
	l.add_theme_font_size_override("font_size", 42 if big else 22)
	l.add_theme_color_override("font_color", Color(0.88, 0.95, 1.0))
	return l
