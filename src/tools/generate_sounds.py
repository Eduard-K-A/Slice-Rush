"""Deterministic sound-effect synthesizer (NumPy -> stdlib wave).

44100 Hz mono 16-bit WAVs, peak 0.8, seeded RNG so regeneration is
byte-reproducible.

Run: python -m src.tools.generate_sounds [output_dir]
"""
from __future__ import annotations

import os
import sys
import wave

import numpy as np

RATE = 44100
PEAK = 0.8


def _write(path: str, samples: np.ndarray) -> None:
    samples = np.clip(samples, -1.0, 1.0) * PEAK
    data = (samples * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(data.tobytes())


def _t(duration_s: float) -> np.ndarray:
    return np.arange(int(RATE * duration_s)) / RATE


def _fade(samples: np.ndarray, fade_s: float = 0.01) -> np.ndarray:
    n = min(int(RATE * fade_s), len(samples) // 2)
    if n > 0:
        ramp = np.linspace(0, 1, n)
        samples[:n] *= ramp
        samples[-n:] *= ramp[::-1]
    return samples


def _tone(freq: float, duration_s: float) -> np.ndarray:
    t = _t(duration_s)
    return _fade(np.sin(2 * np.pi * freq * t))


def _noise_swish(rng: np.random.Generator, decay_per_s: float) -> np.ndarray:
    t = _t(0.09)
    return rng.uniform(-1, 1, len(t)) * np.exp(-decay_per_s * t)


def _bomb(rng: np.random.Generator) -> np.ndarray:
    t = _t(0.5)
    boom = np.sin(2 * np.pi * 55 * t) * np.exp(-6 * t)
    burst_len = int(RATE * 0.12)
    noise = np.zeros_like(t)
    noise[:burst_len] = rng.uniform(-1, 1, burst_len) * np.exp(-30 * t[:burst_len])
    return _fade(boom + 0.6 * noise)


def _sequence(freqs: list[float], tone_s: float) -> np.ndarray:
    return np.concatenate([_tone(f, tone_s) for f in freqs])


def generate(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(7)
    sounds = {
        "slice_1": _noise_swish(rng, 30),
        "slice_2": _noise_swish(rng, 40),
        "slice_3": _noise_swish(rng, 50),
        "bomb": _bomb(rng),
        "beep": _tone(880, 0.12),
        "go": _tone(1245, 0.25),
        "round_clear": _sequence([523, 659, 784], 0.10),
        "game_over": _sequence([392, 311, 262], 0.16),
    }
    written = []
    for name, samples in sounds.items():
        path = os.path.join(out_dir, f"{name}.wav")
        _write(path, samples)
        written.append(path)
    return written


def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "assets/sounds"
    for p in generate(out_dir):
        print("wrote", p)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
