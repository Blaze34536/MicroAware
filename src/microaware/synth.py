"""Synthetic faults mixed onto real (normal) audio, for tests and the simulated Pump B."""
import numpy as np

from .features import SR


def fan(seconds, seed=0, hz=100):
    """Fake fan: rotation tone with harmonics plus broadband noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = sum(0.3 / h * np.sin(2 * np.pi * hz * h * t + rng.uniform(0, 6)) for h in range(1, 6))
    return (x + 0.02 * rng.standard_normal(t.size)).astype(np.float32)


def whine(x, hz=3000, level=0.3):
    """Bearing whine: a tone plus 2 harmonics, slowly rising in pitch."""
    t = np.arange(len(x)) / SR
    f = hz * (1 + 0.02 * t / max(t[-1], 1e-9))
    phase = 2 * np.pi * np.cumsum(f) / SR
    tone = sum(np.sin(h * phase) / h for h in (1, 2, 3))
    return (x + level * x.std() * tone).astype(np.float32)


def rattle(x, rate=8, level=3.0, seed=0):
    """Loose mount: 5-20 ms noise bursts at random times, about `rate` per second."""
    rng = np.random.default_rng(seed)
    y = x.copy()
    for start in rng.integers(0, len(x), int(rate * len(x) / SR)):
        n = int(rng.uniform(0.005, 0.02) * SR)
        seg = y[start : start + n]
        seg += level * x.std() * rng.standard_normal(seg.size).astype(np.float32)
    return y
