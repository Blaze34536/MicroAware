"""Is someone talking? Silero VAD (MIT, snakers4/silero-vad v5.1.2) run offline with onnxruntime."""
from collections import deque
from pathlib import Path

import numpy as np

from .features import SR

MODEL = Path(__file__).parent / "models" / "silero_vad.onnx"
CHUNK, CONTEXT = 512, 64  # the v5 model wants 512 new samples plus the previous 64 at 16 kHz
PROB = 0.5
FRACTION = 0.5  # talking if half of the last second is speech: the fan alone scores 0, synthetic rattle at most 0.35
_session = None


def _vad():
    global _session
    if _session is None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        _session = ort.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])
    return _session


class SpeechTracker:
    """Fed the live audio continuously; the model needs its running state (a fresh start reads fan noise as speech)."""

    def __init__(self):
        self.state = np.zeros((2, 1, 128), np.float32)
        self.context = np.zeros(CONTEXT, np.float32)
        self.pending = np.zeros(0, np.float32)
        self.probs = deque(maxlen=SR // CHUNK)  # the last second

    def feed(self, samples):
        x = np.concatenate([self.pending, np.asarray(samples, np.float32)])
        n = len(x) // CHUNK
        for i in range(n):
            chunk = x[i * CHUNK : (i + 1) * CHUNK]
            out, self.state = _vad().run(None, {"input": np.concatenate([self.context, chunk])[None],
                                                "state": self.state, "sr": np.array(SR, np.int64)})
            self.context = chunk[-CONTEXT:]
            self.probs.append(float(out[0, 0]))
        self.pending = x[n * CHUNK :]

    @property
    def talking(self):
        return len(self.probs) == self.probs.maxlen and np.mean(np.array(self.probs) > PROB) >= FRACTION
