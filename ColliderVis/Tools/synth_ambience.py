"""
synth_ambience.py — generate a mysterious, ethereal, "vibe heaven" ambient drone
and write it to Content/Audio/Source/ambience_loop.wav (replacing the loop).

Design: a lush, floating major-9 pad (A add9 — A C# E G# B), each partial swelling
on its own slow LFO so nothing is rhythmic; a bright, airy filtered-noise shimmer
bed for the "heaven" wash; gentle stereo detune for width; a soft one-pole
low-pass to take any digital edge off. Rendered a touch long and equal-power
crossfaded head<-tail so it loops perfectly seamlessly.

Tuned away from the previous EERIE version: the old loop was A minor-major-7
(a C minor-third clashing against the G# major-7th — the classic horror/suspense
chord) voiced very low and dark. This version swaps the minor third for a MAJOR
third (-> dreamy Amaj9 instead of creepy Am(maj7)), lifts the voicing so it floats
rather than broods, adds upper ninth/third shimmer, brightens the air bed, and
keeps the swells more sustained — mysterious and open, but bright and weightless.

Self-made → CC0 (public domain). After running, re-run Tools/import_audio.py to
rebuild /Game/Audio/S_AmbienceLoop in place.
"""
import math
import wave
from pathlib import Path

import numpy as np

SR = 44100
T = 56.0          # loop length (seconds) — longer so the swells evolve more before repeating
XF = 2.5          # crossfade length (seconds) used to guarantee seamlessness
OUT = Path(__file__).resolve().parent.parent / "Content" / "Audio" / "Source" / "ambience_loop.wav"

# Partials: (freq Hz, weight). A add9/maj9 voicing — A root + fifth/octave + a
# MAJOR third (C#, the un-eerie colour) + major 7th + ninth, with upper third/ninth
# shimmer for the "heaven" sparkle. The root is pulled back so the chord floats
# rather than broods; mid/upper partials carry the ethereal body.
PARTIALS = [
    (55.00, 0.60),   # A1  root        (body, no longer a dominant brooding drone)
    (82.41, 0.46),   # E2  fifth
    (110.00, 0.52),  # A2  octave
    (138.59, 0.48),  # C#3 MAJOR third (replaces the eerie C minor third)
    (164.81, 0.40),  # E3
    (207.65, 0.20),  # G#3 major 7th   (lush & dreamy in a major context — light)
    (246.94, 0.36),  # B3  ninth       (open celestial add9 colour)
    (277.18, 0.24),  # C#4 major third (upper shimmer)
    (329.63, 0.20),  # E4
    (415.30, 0.13),  # G#4 airy shimmer
    (493.88, 0.11),  # B4  high ninth shimmer
]
# Independent slow swell rates (whole cycles over T so they loop) and phases.
LFO_CYCLES = [2, 3, 2, 4, 3, 5, 4, 6, 5, 7, 6]
LFO_PHASE = [0.0, 1.1, 2.3, 0.7, 3.7, 1.9, 4.4, 2.8, 5.5, 0.9, 3.1]

CENTS = 4.0                      # stereo detune (± cents) for width / slow beating
DETUNE = 2.0 ** (CENTS / 1200.0) - 1.0

# Organ / sine-pad timbre: each note is built from sine "drawbar" harmonics
# (fundamental + octave + fifth + double-octave ...), giving a warm pipe-organ
# pad rather than a single pure tone. All sines -> smooth, ethereal.
ORGAN_HARM = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
ORGAN_W = [1.0, 0.60, 0.32, 0.40, 0.16, 0.10]


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


def pink_noise(n, rng):
    """1/f (pink) noise via spectral shaping of white noise."""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0
    spec = spec / np.sqrt(freqs)          # amplitude ~ 1/sqrt(f)  -> pink
    pink = np.fft.irfft(spec, n)
    return pink / (np.max(np.abs(pink)) + 1e-9)


def render(n, detune_sign):
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)
    for (f, w), cyc, ph in zip(PARTIALS, LFO_CYCLES, LFO_PHASE):
        fr = f * (1.0 + detune_sign * DETUNE)
        # Slow amplitude swell with a touch MORE movement than before: a primary
        # slow LFO, modulated by a second even-slower LFO so the swell DEPTH itself
        # breathes (the pattern keeps changing rather than repeating identically).
        # Rides ~0.32..1.0 (deeper than the old near-static 0.45..1.0) but still
        # smooth/ethereal, not a rhythmic pulse.
        prim = 0.5 + 0.5 * np.sin(2.0 * np.pi * (cyc / T) * t + ph)
        sec = 0.5 + 0.5 * np.sin(2.0 * np.pi * ((cyc + 1) / T) * t + ph * 0.6)
        swell = prim * (0.72 + 0.28 * sec)
        lfo = 0.32 + 0.68 * swell
        # Build an organ tone from sine drawbar harmonics.
        tone = np.zeros(n, dtype=np.float64)
        for h, hw in zip(ORGAN_HARM, ORGAN_W):
            tone += hw * np.sin(2.0 * np.pi * fr * h * t)
        out += w * lfo * tone
    return out


def main():
    n_total = int((T + XF) * SR)
    n_loop = int(T * SR)
    n_xf = int(XF * SR)

    left = render(n_total, +1.0)
    right = render(n_total, -1.0)

    # Airy "heaven" bed: white noise → gentle low-pass → very slow amplitude swell.
    # Brighter cutoff than the eerie version (was 150 Hz, dark/rumbly) so the bed
    # reads as a high, breathy shimmer rather than a low wind.
    rng = np.random.default_rng(20260619)
    t = np.arange(n_total) / SR
    bed_env = 0.5 + 0.5 * np.sin(2.0 * np.pi * (1.0 / T) * t + 0.5)
    for chan, seedoff in ((left, 0.0), (right, 7.0)):
        noise = rng.standard_normal(n_total)
        noise = one_pole_lpf(noise, 900.0)        # airy, breathy shimmer bed
        noise /= (np.max(np.abs(noise)) + 1e-9)
        chan += 0.013 * (0.4 + 0.6 * bed_env) * noise   # subtle wash

    # Soft PINK-NOISE WAVES beneath the music: warm 1/f noise gently rolled off,
    # swelling in slow waves (a few cycles over the loop) so it breathes under the pad.
    for chan, seedoff in ((left, 3.0), (right, 11.0)):
        pink = pink_noise(n_total, np.random.default_rng(20260621 + int(seedoff)))
        pink = one_pole_lpf(pink, 2200.0)                 # warm, soft
        pink /= (np.max(np.abs(pink)) + 1e-9)
        waves = 0.4 + 0.6 * (0.5 + 0.5 * np.sin(2.0 * np.pi * (3.0 / T) * t + seedoff))
        chan += 0.06 * waves * pink                       # soft, underneath

    stereo = [left, right]
    # Gentle global low-pass: opened up vs the eerie version (was 5500 Hz) to let
    # more air/sparkle through → bright and ethereal rather than dark.
    stereo = [one_pole_lpf(c, 8500.0) for c in stereo]

    # Equal-power crossfade: blend the tail (n_loop..n_loop+n_xf) into the head so
    # the n_loop-length result loops with no click.
    fade = np.linspace(0.0, 1.0, n_xf)
    fin = np.sin(fade * (math.pi / 2.0))
    fout = np.cos(fade * (math.pi / 2.0))
    chans = []
    for c in stereo:
        head = c[:n_loop].copy()
        tail = c[n_loop:n_loop + n_xf]
        head[:n_xf] = head[:n_xf] * fin + tail * fout
        chans.append(head)

    mix = np.stack(chans, axis=1)
    peak = np.max(np.abs(mix)) + 1e-9
    mix = mix / peak * 0.72                       # headroom; engine plays it at ~0.35
    pcm = (mix * 32767.0).astype(np.int16)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    print(f"wrote {OUT}  {n_loop/SR:.1f}s  {pcm.shape[0]} frames  peak~0.72  stereo 16-bit {SR}Hz")


if __name__ == "__main__":
    main()
