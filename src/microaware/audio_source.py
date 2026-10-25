"""Live audio into the engine: the real mic, or the synthetic fan when no hardware is around."""
import threading
import time

import soundfile as sf
from scipy.signal import resample_poly

import numpy as np

from . import synth
from .features import SR

CHUNK = 0.1  # seconds per delivered block


def start_mic(on_audio):
    import sounddevice as sd  # needs libportaudio (see run.sh)

    stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=int(CHUNK * SR),
                            callback=lambda data, *_: on_audio(data[:, 0].copy()))
    stream.start()
    return stream


def start_synth(on_audio):
    audio = synth.fan(30)  # 30 s holds whole cycles of the 100 Hz tone, so the loop point doesn't click
    n = int(CHUNK * SR)

    def loop():
        i = 0
        while True:
            on_audio(audio[i : i + n])
            i = (i + n) % len(audio)
            time.sleep(CHUNK)

    threading.Thread(target=loop, daemon=True).start()


def start_file(on_audio, path):
    """Replay a WAV in real time through the same pipeline, looping. For rehearsals and as a demo fallback."""
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if sr != SR:
        audio = resample_poly(audio, SR, sr).astype(np.float32)
    n = int(CHUNK * SR)

    def loop():
        i = 0
        while True:
            on_audio(audio[i : i + n])
            i = 0 if i + n >= len(audio) else i + n
            time.sleep(CHUNK)

    threading.Thread(target=loop, daemon=True).start()


def recorder(on_audio, path):
    """Wrap on_audio so every chunk is also written to a WAV; returns (wrapped, close)."""
    f = sf.SoundFile(path, "w", samplerate=SR, channels=1)

    def tee(chunk):
        f.write(chunk)
        on_audio(chunk)

    return tee, f.close
