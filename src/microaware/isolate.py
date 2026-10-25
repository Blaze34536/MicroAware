"""ElevenLabs Voice Isolator: finds the voice in suspicious audio so the detector can leave it out."""
import io

import httpx
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, resample_poly

from .features import SR

URL = "https://api.elevenlabs.io/v1/audio-isolation"
MIN_SECONDS = 5.0  # the API rejects anything under 4.6 s
MAX_LAG = SR // 10  # the MP3 it returns starts a few ms late; search up to 100 ms


def isolate(audio, api_key, timeout=30):
    """The voice in `audio` (16 kHz float), time-aligned to it, and the credits it cost. Raises on any failure."""
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    r = httpx.post(URL, headers={"xi-api-key": api_key}, files={"audio": ("audio.pcm", pcm)},
                   data={"file_format": "pcm_s16le_16"}, timeout=timeout)
    r.raise_for_status()
    voice, sr = sf.read(io.BytesIO(r.content), dtype="float32", always_2d=True)
    voice = resample_poly(voice.mean(axis=1), SR, sr).astype(np.float32)
    return align(audio, voice), int(r.headers.get("character-cost", 0))


def align(audio, voice):
    """Shift `voice` to line up with `audio` and trim or pad it to the same length."""
    n = len(audio)
    voice = np.pad(voice, (0, max(0, n - len(voice))))[:n]
    corr = fftconvolve(audio, voice[::-1], mode="full")[n - 1 - MAX_LAG : n + MAX_LAG]
    lag = int(np.argmax(corr)) - MAX_LAG
    out = np.zeros_like(voice)
    if lag >= 0:
        out[lag:] = voice[: n - lag]
    else:
        out[:lag] = voice[-lag:]
    return out
