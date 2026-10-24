"""Live audio into the engine: the real mic, or the synthetic fan when no hardware is around."""
import threading
import time

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
    def loop():
        i = 0
        while True:
            on_audio(synth.fan(CHUNK, seed=i))
            i += 1
            time.sleep(CHUNK)

    threading.Thread(target=loop, daemon=True).start()
