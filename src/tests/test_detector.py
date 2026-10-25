import numpy as np

from microaware import features, synth
from microaware.detector import Detector
from microaware.synth import fan


def test_window_features_shape():
    assert features.window_features(fan(1.0, 0)).shape == (features.N_MELS * features.STACK,)


def test_normal_audio_stays_under_threshold():
    det = Detector.fit(fan(90, 1))
    scores = [det.score(w) for w in features.windows(fan(20, 2))]
    assert max(scores) < det.threshold


def test_synthetic_faults_cross_threshold():
    det = Detector.fit(fan(90, 1))
    for fault in (synth.whine, synth.rattle):
        scores = [det.score(w) for w in features.windows(fault(fan(10, 3)))]
        assert np.median(scores) > det.threshold, fault.__name__


def test_top_bands_point_at_whine_frequency():
    det = Detector.fit(fan(90, 1))
    w = next(features.windows(synth.whine(fan(2, 4), hz=3000)))
    lo, hi = det.top_bands(w)[0]["band_hz"]
    assert lo <= 3000 * 1.1 and hi >= 3000 * 0.9
