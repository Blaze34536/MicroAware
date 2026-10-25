"""Names the fault once the detector says something is wrong. Trained on a few recorded clips per fault."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import features

NORMAL = "normal"


def _augment(x, rng):
    """Gain +-6 dB and a little room noise, so a handful of clips covers more conditions."""
    out = [x]
    for _ in range(4):
        y = x * 10 ** (rng.uniform(-6, 6) / 20)
        out.append((y + rng.uniform(0.002, 0.01) * x.std() * rng.standard_normal(x.size)).astype(np.float32))
    return out


class Labeler:
    def __init__(self, model, min_conf=0.6):
        self.model, self.min_conf = model, min_conf

    @classmethod
    def fit(cls, normal_audio, clips, seed=0):
        """clips: {label: [audio arrays]}. Normal audio is its own class so it never gets a fault name."""
        rng = np.random.default_rng(seed)
        X, y = [], []
        for label, audios in [(NORMAL, [normal_audio])] + list(clips.items()):
            for audio in audios:
                for aug in _augment(audio, rng):
                    for w in features.windows(aug):
                        X.append(features.window_features(w))
                        y.append(label)
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
        model.fit(np.array(X), y)
        return cls(model)

    @property
    def labels(self):
        return [c for c in self.model.classes_ if c != NORMAL]

    def predict(self, window):
        """(label or None, confidence). None means normal or not confident: report 'unknown anomaly'."""
        probs = self.model.predict_proba(features.window_features(window)[None])[0]
        i = int(np.argmax(probs))
        label, conf = self.model.classes_[i], float(probs[i])
        return (None if label == NORMAL or conf < self.min_conf else label), round(conf, 2)


def simulated_clips(normal_audio, seconds=10):
    """{fault: [clips]}: each simulated fault mixed into three stretches of the normal sound."""
    from .synth import FAULTS

    n = int(seconds * features.SR)
    starts = np.linspace(0, max(0, len(normal_audio) - n), 3).astype(int)
    return {name: [fault(normal_audio[s : s + n], t0=s / features.SR) for s in starts] for name, fault in FAULTS.items()}
