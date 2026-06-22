"""
synth_event_fx.py — generate two event SFX for ColliderVis:
  * event_sweep.wav : a big RESONANT filter sweep (riser) for each new collision —
                      broadband noise through a resonant low-pass whose cutoff sweeps
                      up, so a resonant peak whistles upward. Pairs with the in-engine
                      ambience LPF sweep for a large, resonant "whoosh".
  * thud.wav        : a big low impact "thud" for each click (pitch-dropping sine +
                      transient click, fast decay).
Self-made -> CC0. After running, re-run Tools/import_audio.py to rebuild the assets.
"""
import wave
from pathlib import Path
import numpy as np

SR = 44100
SRC = Path(__file__).resolve().parent.parent / "Content" / "Audio" / "Source"


def svf_lowpass(x, fc, q):
    """TPT state-variable low-pass with per-sample cutoff fc (array) and resonance q."""
    n = len(x)
    out = np.empty(n)
    ic1 = ic2 = 0.0
    inv_q = 1.0 / q
    for i in range(n):
        g = np.tan(np.pi * min(fc[i], SR * 0.45) / SR)
        a1 = 1.0 / (1.0 + g * (g + inv_q))
        a2 = g * a1
        a3 = g * a2
        v3 = x[i] - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        out[i] = v2
    return out


def write_wav(path, mono):
    mono = mono / (np.max(np.abs(mono)) + 1e-9) * 0.9
    pcm = (mono * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {path}  {len(mono)/SR:.2f}s")


def make_sweep():
    dur = 1.7
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    src = rng.standard_normal(n)                       # broadband noise
    a = t / dur
    cutoff = 180.0 * (9000.0 / 180.0) ** a             # exp sweep 180 -> 9000 Hz
    swept = svf_lowpass(src, cutoff, q=9.0)            # strong resonance
    env = np.minimum(1.0, t / 0.06) * np.clip(1.0 - (a - 0.85) / 0.15, 0.0, 1.0)
    write_wav(SRC / "event_sweep.wav", swept * env)


def make_thud():
    # Big, bassy 808-style kick for each new collision: a punchy pitch-dropping
    # body (the "boom"), a long sustained deep sub layer (the 808 weight), and a
    # short attack transient (the "knock"), with gentle saturation for harmonics
    # so the low end still reads on phone/laptop speakers.
    dur = 1.1
    n = int(dur * SR)
    t = np.arange(n) / SR

    # Body: fast exponential pitch drop 150 -> 48 Hz over ~45 ms — the classic 808 boom.
    f0, f1 = 150.0, 48.0
    pitch = f1 + (f0 - f1) * np.exp(-t / 0.045)
    body_phase = 2.0 * np.pi * np.cumsum(pitch) / SR
    body = np.sin(body_phase) * np.exp(-t / 0.40)

    # Sub: a steady deep ~38 Hz fundamental with a long tail — the bass weight.
    # A touch of 2nd harmonic so it survives on speakers that can't reach 38 Hz.
    sub_f = 38.0
    sub = np.sin(2.0 * np.pi * sub_f * t) * np.exp(-t / 0.62)
    sub += 0.35 * np.sin(2.0 * np.pi * 2.0 * sub_f * t) * np.exp(-t / 0.45)

    # Attack: short noise burst + a high sine click for the transient "knock".
    rng = np.random.default_rng(3)
    click = (rng.standard_normal(n) * 0.6
             + np.sin(2.0 * np.pi * 1600.0 * t)) * np.exp(-t / 0.006)

    thud = 0.70 * body + 1.00 * sub + 0.22 * click
    thud = np.tanh(thud * 1.4)   # gentle saturation = harmonics = "bigger", tames peaks
    write_wav(SRC / "thud.wav", thud)


if __name__ == "__main__":
    SRC.mkdir(parents=True, exist_ok=True)
    make_sweep()
    make_thud()
