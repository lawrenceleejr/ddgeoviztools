# ColliderVis — Audio Credits & License Manifest

All bundled sound effects are **CC0 1.0 (Creative Commons Zero / Public Domain)**.
CC0 waives all copyright and related rights worldwide: the files may be used for
any purpose, commercial or non-commercial, **with no attribution required**. The
attribution below is provided as a courtesy and for provenance, not as an
obligation.

These are placeholder/default sounds chosen because they are license-clean for
any use. Replace them freely — see "Audio — replacing sounds" in the project
README and `Tools/import_audio.py`.

| File (`Content/Audio/Source/`) | Imported asset (`/Game/Audio/`) | Author | Source URL | License | Notes |
|---|---|---|---|---|---|
| `ui_click.wav` | `S_UIClick` | qubodup (Iwan Gabovitch) | https://opengameart.org/content/button-click-sound-effect-cc0public-domain | CC0 1.0 | From `qubodup-click.zip` (`qubodup-click1.wav`). |
| `ui_hover.wav` | `S_UIHover` | qubodup (Iwan Gabovitch) | https://opengameart.org/content/button-click-sound-effect-cc0public-domain | CC0 1.0 | From `qubodup-click.zip` (`qubodup-hover1.wav`). |
| `splash_whoosh.wav` | `S_SplashWhoosh` | ColliderVis (synthesized) | `Tools/synth_whoosh.py` | CC0 1.0 | Self-made soft/mellow swell (heavily low-passed air bed + warm low body under a smooth raised-cosine envelope, no harsh transient). Plays at the splash intro AND on each new-event draw, so kept subtle/non-fatiguing; engine plays it at ~0.35–0.45 volume. Replaced the original harsh qubodup "Air whoosh" (whoosh2.wav) which was too sharp/pulsating on repeat. Regenerate with `python Tools/synth_whoosh.py`. |
| `ambience_loop.wav` | `S_AmbienceLoop` | ColliderVis (synthesized) | `Tools/synth_ambience.py` | CC0 1.0 | Self-made mysterious/ethereal "vibe heaven" drone: lush floating A add9/maj9 (A C# E G# B — major third, NOT the old eerie minor-major-7), per-partial slow swells (non-rhythmic), bright airy filtered-noise shimmer bed, stereo detune; 40 s seamless (equal-power crossfade). Regenerate with `python Tools/synth_ambience.py`. |

## License text (CC0 1.0)

> The person who associated a work with this deed has dedicated the work to the
> public domain by waiving all of his or her rights to the work worldwide under
> copyright law, including all related and neighboring rights, to the extent
> allowed by law. You can copy, modify, distribute and perform the work, even for
> commercial purposes, all without asking permission.

Full text: https://creativecommons.org/publicdomain/zero/1.0/

## Provenance / verification notes

- All files were downloaded from OpenGameArt.org pages that display the **CC0**
  license badge. Licenses were verified on each source page before inclusion.
- Format on disk: 16-bit PCM WAV, 44.1 kHz, stereo (verified with `file`).
- Original filenames are preserved in the "Notes" column above so the canonical
  ColliderVis names map back to their upstream source.

### Items considered but SKIPPED

- `60 CC0 Sci-Fi SFX` (https://opengameart.org/content/60-cc0-sci-fi-sfx) —
  CC0, but the pack ships `.ogg` files only (no WAV) and contained no clean
  ambience loop, so it was not used. (The required deliverable is WAV.)
