"""Autoencoder that learns the normal machine sound; what it can't reconstruct is the anomaly."""
import numpy as np
from sklearn.neural_network import MLPRegressor

from . import features


class Detector:
    def __init__(self, mean, std, model, threshold):
        self.mean, self.std, self.model, self.threshold = mean, std, model, threshold

    @classmethod
    def fit(cls, audio, seed=0):
        X = np.array([features.window_features(w) for w in features.windows(audio)])
        mean, std = X.mean(axis=0), X.std(axis=0) + 1e-3
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

    def residual(self, window):
        """Per-mel-band residual in dB (input minus reconstruction), averaged over chunks."""
        z = self._z(window)
        diff_db = (z - self.model.predict(z[None])[0]) * self.std
        return diff_db.reshape(features.STACK, features.N_MELS).mean(axis=0)

    def top_bands(self, window, n=3):
        r = self.residual(window)
        return [{"band_hz": features.band_hz(i), "delta_db": round(float(r[i]), 1)} for i in np.argsort(r)[::-1][:n]]
