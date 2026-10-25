from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from microaware import features, synth
from microaware.detector import Detector
from microaware.engine import Engine

FIX = Path(__file__).parent / "fixtures"
SPEECH = sf.read(FIX / "speech.wav", dtype="float32")[0]
FAN = sf.read(Path(__file__).parents[1] / "static" / "sounds" / "fan_normal.ogg", dtype="float32")[0]  # real fan, CC BY 4.0 (static/sounds/CREDITS.md)
TRAIN, TEST = FAN[: 30 * features.SR], FAN[30 * features.SR :]


def talking(db=0, lead=8):
    """`lead` s of real fan, then the speech `db` relative to the fan, then fan to the end. Returns (mix, voice)."""
    voice = np.zeros_like(TEST)
    start = lead * features.SR
    voice[start : start + len(SPEECH)] = TEST.std() / SPEECH.std() * 10 ** (db / 20) * SPEECH
    return TEST + voice, voice


class FakeIsolator:
    """Returns the true voice for whatever slice of `mix` it is sent, like a perfect Voice Isolator."""

    def __init__(self, mix, voice, fail=False):
        self.mix, self.voice, self.fail, self.calls = mix, voice, fail, []

    def __call__(self, audio):
        self.calls.append(len(audio) / features.SR)
        if self.fail:
            raise OSError("network down")
        for s in np.flatnonzero(self.mix == audio[0]):
            if np.array_equal(self.mix[s : s + len(audio)], audio):
                return self.voice[s : s + len(audio)], 55
        raise AssertionError("audio not from the test mix")


@pytest.fixture(scope="module")
def det():
    return Detector.fit(TRAIN)


def test_masked_score_ignores_the_voice_but_not_a_fault(det):
    mix, voice = talking()
    pairs = list(zip(features.windows(mix[8 * features.SR :][: len(SPEECH)]), features.windows(voice[8 * features.SR :][: len(SPEECH)])))
    assert max(det.score(m) for m, _ in pairs) > 2 * det.threshold  # the voice alone would alert
    assert max(det.score_masked(m, v)[0] for m, v in pairs) < 2 * det.threshold
    whined = [(synth.whine(m), v) for m, v in pairs]
    assert min(det.score_masked(m, v)[0] for m, v in whined) > 2 * det.threshold


def test_masked_score_without_voice_is_the_normal_score(det):
    w = TEST[: features.SR]
    score, voiced, _ = det.score_masked(w, np.zeros_like(w))
    assert voiced == 0 and score == pytest.approx(det.score(w), rel=1e-6)


def run(eng, audio):
    half = features.SR // 2
    for i in range(len(audio) // half):
        eng.push(audio[i * half : (i + 1) * half])
        eng.step()
    eng.drain()


def engine(tmp_path, det, isolator):
    eng = Engine(data_dir=tmp_path, isolator=isolator)
    eng.detector = det
    return eng


@pytest.mark.parametrize("db", [0, -6, -10])  # Silero misses most of -6 dB and nearly all of -10 dB on this fan
def test_talking_is_checked_with_the_isolator_and_raises_no_alert(tmp_path, det, db):
    mix, voice = talking(db)
    iso = FakeIsolator(mix, voice)
    eng = engine(tmp_path, det, iso)
    run(eng, mix)
    assert iso.calls and min(iso.calls) >= 4.6  # the API rejects shorter clips
    assert eng.alerts.alerts == []
    assert eng.isolate_spent == 55 * len(iso.calls)


def test_fault_during_talking_still_alerts(tmp_path, det):
    mix, voice = talking()
    whined = mix.copy()
    whined[10 * features.SR :] = synth.whine(mix[10 * features.SR :])  # starts 2 s into the talking
    eng = engine(tmp_path, det, FakeIsolator(whined, voice))
    run(eng, whined[: 20 * features.SR])  # stop while still talking
    assert eng.alerts.alerts


@pytest.mark.parametrize("fault", [synth.whine, synth.rattle, synth.hiss])
def test_fault_without_talking_still_alerts_and_stops_checking_once_raised(tmp_path, det, fault):
    faulty = TEST.copy()
    faulty[4 * features.SR :] = fault(TEST[4 * features.SR :])
    iso = FakeIsolator(faulty, np.zeros_like(faulty))
    eng = engine(tmp_path, det, iso)
    run(eng, faulty)
    assert eng.alerts.alerts and eng.alerts.alerts[0]["evidence"]["voice_removed"] is False
    assert len(iso.calls) <= 2  # no checks once the alert is active


def test_isolator_failure_falls_back_to_alerting_without_it(tmp_path, det):
    mix, voice = talking()
    whined = mix.copy()
    whined[10 * features.SR :] = synth.whine(mix[10 * features.SR :])
    iso = FakeIsolator(whined, voice, fail=True)
    eng = engine(tmp_path, det, iso)
    run(eng, whined)
    assert iso.calls and eng.alerts.alerts


def test_credit_cap_stops_isolating(tmp_path, det):
    mix, voice = talking()
    iso = FakeIsolator(mix, voice)
    eng = engine(tmp_path, det, iso)
    eng.isolate_budget = 0
    run(eng, mix)
    assert iso.calls == []


def test_real_isolator_output_keeps_talking_quiet_and_faults_loud(det):
    """Real Voice Isolator output for three 5 s clips of talking(0). It is imperfect (it leaks some fan), which
    broke an earlier masking method that dropped frames: the frames left over were quieter than normal."""
    iso = sf.read(FIX / "isolated_talk.flac", dtype="float32")[0]
    mix, _ = talking(0)
    for fault in (None, synth.whine):
        over = []
        for k in range(3):
            seg, v = mix[int((7.5 + 5 * k) * features.SR) :][: 5 * features.SR], iso[k * 5 * features.SR :][: 5 * features.SR]
            seg = fault(seg) if fault else seg
            over += [det.score_masked(w, wv)[0] > 2 * det.threshold for w, wv in zip(features.windows(seg), features.windows(v))]
        runs = max(len(r) for r in "".join("x" if o else " " for o in over).split(" "))
        if fault:
            assert np.mean(over) > 0.8
        else:
            assert runs < 3  # an alert needs 3 in a row
