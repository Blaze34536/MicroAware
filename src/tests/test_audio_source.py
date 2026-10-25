import time

import numpy as np
import soundfile as sf

from microaware import audio_source, synth
from microaware.features import SR


def test_file_source_replays_wav_resampled_to_16k(tmp_path):
    path = tmp_path / "run.wav"
    sf.write(path, np.tile(synth.fan(1.0), 1)[:SR].repeat(3), SR * 3)  # 48 kHz file
    got = []
    audio_source.start_file(got.append, path)
    deadline = time.time() + 2
    while sum(map(len, got)) < SR // 2 and time.time() < deadline:
        time.sleep(0.02)
    assert sum(map(len, got)) >= SR // 2 and got[0].dtype == np.float32


def test_recorder_tees_audio_to_wav(tmp_path):
    path = tmp_path / "rec.wav"
    got = []
    tee, close = audio_source.recorder(got.append, path)
    tee(np.ones(1600, np.float32) * 0.1)
    tee(np.ones(1600, np.float32) * 0.1)
    close()
    data, sr = sf.read(path, dtype="float32")
    assert sr == SR and len(data) == 3200 and len(got) == 2
