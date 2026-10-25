"""Autoencoder that learns the normal machine sound; what it can't reconstruct is the anomaly."""
import numpy as np
from sklearn.neural_network import MLPRegressor

from . import features

VOICE_SHARE_DB = -20  # leave out chunk-bands where the isolated voice is over 1% of the power
STD_FLOOR_DB = 0.5  # a mic level wobbles ~0.5 dB; a steadier baseline band is not real precision (synthetic fans go to 0.01)


class Detector:
    def __init__(self, mean, std, model, threshold):
        self.mean, self.std, self.model, self.threshold = mean, std, model, threshold

    @classmethod
    def fit(cls, audio, seed=0):
        X = np.array([features.window_features(w) for w in features.windows(audio)])
        mean, std = X.mean(axis=0), np.maximum(X.std(axis=0), STD_FLOOR_DB)
        Z = (X - mean) / std
        rng = np.random.default_rng(seed)
        idx = rng.permutation(len(Z))
        cut = int(0.8 * len(Z))
        model = MLPRegressor(hidden_layer_sizes=(64, 16, 64), max_iter=2000, random_state=seed)
        model.fit(Z[idx[:cut]], Z[idx[:cut]])
        det = cls(mean, std, model, 0.0)
        held = [det._error(z) for z in Z[idx[cut:]]]
        det.threshold = float(np.percentile([e.mean() for e in held], 99) * 1.3)
        return det

    def _error(self, z):
        return (z - self.model.predict(z[None])[0]) ** 2

    def _z(self, window):
        return (features.window_features(window) - self.mean) / self.std

    def score(self, window):
        return float(self._error(self._z(window)).mean())

    def score_masked(self, window, voice):
        """Score with the parts the voice touches left out. Returns (score, fraction left out, top bands)."""
        kept = features.voice_share_db(window, voice) < VOICE_SHARE_DB
        if not kept.any():
            return 0.0, 1.0, []
        z = self._z(window)
        z[~kept] = 0  # the voice hid these: assume normal
        diff_db = np.where(kept, z - self.model.predict(z[None])[0], 0) * self.std
        return float(self._error(z)[kept].mean()), float(1 - kept.mean()), self._top(diff_db)

    def residual(self, window):
        """Per-mel-band residual in dB (input minus reconstruction), averaged over chunks."""
        z = self._z(window)
        diff_db = (z - self.model.predict(z[None])[0]) * self.std
        return diff_db.reshape(features.STACK, features.N_MELS).mean(axis=0)

    def top_bands(self, window, n=3):
        return self._top((self._z(window) - self.model.predict(self._z(window)[None])[0]) * self.std, n)

    @staticmethod
    def _top(diff_db, n=3):
        r = diff_db.reshape(features.STACK, features.N_MELS).mean(axis=0)
        return [{"band_hz": features.band_hz(i), "delta_db": round(float(r[i]), 1)} for i in np.argsort(r)[::-1][:n]]
