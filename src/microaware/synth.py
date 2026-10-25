"""Synthetic faults mixed onto real (normal) audio, for tests and the simulated Pump B."""
import numpy as np

from .features import SR


def fan(seconds, seed=0, hz=100):
    """Fake fan: rotation tone with harmonics plus broadband noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = sum(0.3 / h * np.sin(2 * np.pi * hz * h * t + rng.uniform(0, 6)) for h in range(1, 6))
    return (x + 0.02 * rng.standard_normal(t.size)).astype(np.float32)


def whine(x, hz=3000, level=0.3, t0=0.0):
    """Bearing whine: a tone plus 2 harmonics, slowly rising in pitch. t0 keeps phase continuous across chunks."""
    t = t0 + np.arange(len(x)) / SR
    phase = 2 * np.pi * hz * (t + 0.001 * t**2)  # pitch rises 0.2% per second
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


def hiss(x, level=0.3, lo=3000, seed=0):
    """Air leak: steady broadband noise above `lo` Hz."""
    from scipy.signal import butter, sosfilt

    n = sosfilt(butter(4, lo, "highpass", fs=SR, output="sos"), np.random.default_rng(seed).standard_normal(len(x)))
    return (x + level * x.std() * n / n.std()).astype(np.float32)


def imbalance(x, hz=30, level=3.0, t0=0.0):
    """Tape flag on a blade: a slap once per revolution plus a loudness wobble at the rotation rate.
    The subtlest of the simulated faults: about 3x the threshold on a real fan, where the others reach 20-80x."""
    t = t0 + np.arange(len(x)) / SR
    slap = np.exp(-((t * hz) % 1.0) / 0.1) * np.sin(2 * np.pi * 900 * t)  # ~3 ms decaying 900 Hz burst
    return (x * (1 + 0.5 * np.sin(2 * np.pi * hz * t)) + level * x.std() * slap).astype(np.float32)


# Fault name -> fn(audio, t0): t0 is the audio's start time in seconds, so faults stay continuous across chunks.
FAULTS = {
    "imbalance": lambda x, t0=0.0: imbalance(x, t0=t0),
    "bearing": lambda x, t0=0.0: whine(x, t0=t0),
    "loose_mount": lambda x, t0=0.0: rattle(x, seed=int(t0 * SR)),
    "air_leak": lambda x, t0=0.0: hiss(x, seed=int(t0 * SR)),
}
