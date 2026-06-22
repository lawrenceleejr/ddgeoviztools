"""
synth_whoosh.py — generate a soft, mellow "swell" cue and write it to
Content/Audio/Source/splash_whoosh.wav (replacing the harsh downloaded air whoosh).

This sound plays at the splash intro AND on every new-event draw (both reference
/Game/Audio/S_SplashWhoosh), so it needs to be subtle and non-fatiguing on repeat.

Design (deliberately mellow, NOT a sharp whoosh):
  * A gentle filtered-noise "air" swell — heavily low-passed so there's no harsh
    sibilance/hiss — under a smooth raised-cosine envelope (slow attack, soft
    release, no transient click).
  * A faint warm low sine body (~140 Hz) with a slight downward glide for a soft
    sense of motion, mixed well under the air.
  * Global low-pass to round off any edge. Stereo, soft peak (engine plays it at
    ~0.35–0.45 volume on top of this).

Self-made → CC0 (public domain). After running, re-run Tools/import_audio.py to
rebuild /Game/Audio/S_SplashWhoosh in place.
"""
import math
import wave
from pathlib import Path

import numpy as np

SR = 44100
T = 2.2                       # total length (seconds) — short, soft cue
OUT = Path(__file__).resolve().parent.parent / "Content" / "Audio" / "Source" / "splash_whoosh.wav"


def one_pole_lpf(x, cutoff_hz):
    """Simple one-pole low-pass for a soft, airy top end."""
    a = math.exp(-2.0 * math.pi * cutoff_hz / SR)
    y = np.empty_like(x)
    acc = 0.0
    b = 1.0 - a
    for i in range(x.shape[0]):
        acc = b * x[i] + a * acc
        y[i] = acc
    return y


def render(n, rng, seed_noise, glide_sign):
    t = np.arange(n) / SR
    # Smooth raised-cosine envelope: slow-ish attack (~35%), gentle release.
    env = 0.5 - 0.5 * np.cos(2.0 * np.pi * t / T)        # 0 → 1 → 0, no clicks
    env = env ** 1.3                                      # bias toward a softer, later peak

    # Warm low body with a slight downward glide (mellow motion, not a sweep).
    f0 = 150.0
    f1 = 120.0
    inst_f = np.linspace(f0, f1, n) * (1.0 + 0.0008 * glide_sign)  # tiny stereo detune
    phase = 2.0 * np.pi * np.cumsum(inst_f) / SR
    body = np.sin(phase) * 0.35

    # Airy noise bed — low-passed hard so it's a soft breath, not hiss.
    noise = seed_noise.copy()
    noise = one_pole_lpf(noise, 1400.0)
    noise /= (np.max(np.abs(noise)) + 1e-9)

    mix = env * (body + 0.55 * noise)
    return one_pole_lpf(mix, 5000.0)                      # round off the edge


def main():
    n = int(T * SR)
    rng = np.random.default_rng(20260620)
    nl = rng.standard_normal(n)
    nr = rng.standard_normal(n)

    left = render(n, rng, nl, +1.0)
    right = render(n, rng, nr, -1.0)

    mix = np.stack([left, right], axis=1)
    peak = np.max(np.abs(mix)) + 1e-9
    mix = mix / peak * 0.5                                # soft headroom; engine plays at ~0.35–0.45

    pcm = (mix * 32767.0).astype(np.int16)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    print(f"wrote {OUT}  {T:.1f}s  {pcm.shape[0]} frames  peak~0.5  stereo 16-bit {SR}Hz")


if __name__ == "__main__":
    main()
