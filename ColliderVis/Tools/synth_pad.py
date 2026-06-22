"""synth_pad.py — a soft, reverb-y activation chime for the elevator call-pad.
Inharmonic bell partials with a long diffuse tail (cheap multi-tap reverb).
Self-made -> CC0. After running, re-import audio so /Game/Audio/S_PadPing rebuilds."""
import wave
from pathlib import Path
import numpy as np

SR = 44100
SRC = Path(__file__).resolve().parent.parent / "Content" / "Audio" / "Source"


def write_wav(path, mono):
    mono = mono / (np.max(np.abs(mono)) + 1e-9) * 0.9
    pcm = (mono * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {path}  {len(mono)/SR:.2f}s")


def make_pad_ping():
    # Dry bell: a few inharmonic partials with a fast-ish decay.
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    ping = (1.00 * np.sin(2 * np.pi * 784.0 * t) +
            0.55 * np.sin(2 * np.pi * 1174.0 * t) +
            0.30 * np.sin(2 * np.pi * 1568.0 * t) +
            0.18 * np.sin(2 * np.pi * 2350.0 * t)) * np.exp(-t / 0.16)

    # Cheap diffuse reverb: many decaying, jittered delayed copies of the ping.
    total = int(2.2 * SR)
    out = np.zeros(total)
    out[:n] += ping * 0.9
    rng = np.random.default_rng(11)
    for k in range(1, 90):
        delay = int((0.012 * k + rng.uniform(0.0, 0.008)) * SR)
        if delay + n > total:
            break
        gain = 0.7 * np.exp(-0.055 * k) * rng.uniform(0.5, 1.0)
        out[delay:delay + n] += ping * gain
    # gentle overall tail envelope so it fades smoothly
    out *= np.exp(-np.arange(total) / (0.9 * SR)) + 0.02
    write_wav(SRC / "pad_ping.wav", out)


if __name__ == "__main__":
    SRC.mkdir(parents=True, exist_ok=True)
    make_pad_ping()
