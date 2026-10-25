"""Audio windows -> log-mel feature vectors."""
import numpy as np
from scipy.signal import stft

SR = 16_000
N_FFT = 1024
HOP = 256
N_MELS = 64
STACK = 5  # each 1 s window is summarized as 5 consecutive chunks of mel frames


def _mel(hz):
    return 2595 * np.log10(1 + np.asarray(hz) / 700)


def _hz(mel):
    return 700 * (10 ** (np.asarray(mel) / 2595) - 1)


# Band edges in Hz: band i spans EDGES[i]..EDGES[i + 2], peaking at EDGES[i + 1].
EDGES = _hz(np.linspace(_mel(20), _mel(SR / 2), N_MELS + 2))


def _filterbank():
    bins = np.fft.rfftfreq(N_FFT, 1 / SR)
    fb = np.zeros((N_MELS, bins.size))
    for i in range(N_MELS):
        lo, mid, hi = EDGES[i : i + 3]
        fb[i] = np.clip(np.minimum((bins - lo) / (mid - lo), (hi - bins) / (hi - mid)), 0, None)
    return fb


FB = _filterbank()


def band_hz(i):
    return (float(EDGES[i]), float(EDGES[i + 2]))


def logmel(x):
    """(N_MELS, frames) log-mel energies in dB."""
    _, _, z = stft(x, fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP, boundary=None, padded=False)
    return 10 * np.log10(FB @ np.abs(z) ** 2 + 1e-10)


def window_features(x):
    """One 1 s window -> flat vector of STACK chunk-averaged mel spectra."""
    chunks = np.array_split(logmel(x), STACK, axis=1)
    return np.concatenate([c.mean(axis=1) for c in chunks])


def windows(x, length=1.0, step=0.5):
    n, s = int(length * SR), int(step * SR)
    for start in range(0, len(x) - n + 1, s):
        yield x[start : start + n]



def voice_share_db(x, voice):
    """How much of each chunk-band's power is the voice, in dB (0 = all of it). Power-averaged so bursts count."""
    power = lambda a: np.concatenate([c.mean(axis=1) for c in np.array_split(10 ** (logmel(a) / 10), STACK, axis=1)])
    return 10 * np.log10(power(voice) / power(x) + 1e-12)
