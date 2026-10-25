from pathlib import Path

import numpy as np
import soundfile as sf

from microaware import features, synth
from microaware.engine import Engine
from microaware.speech import SpeechTracker

SPEECH = sf.read(Path(__file__).parent / "fixtures" / "speech.wav", dtype="float32")[0]  # ElevenLabs TTS, 16 kHz


def over_fan(speech, db, seed=0):
    """Speech mixed onto the fake fan, `db` louder (or quieter, if negative) than the fan."""
    fan = synth.fan(len(speech) / features.SR, seed)
    gain = fan.std() / speech.std() * 10 ** (db / 20)
    return fan + gain * speech


def flagged(audio):
    """Talking or not after each 0.5 s, fed like the live loop, after 2 s of fan to settle."""
    tracker, half = SpeechTracker(), features.SR // 2
    tracker.feed(synth.fan(2, seed=99))
    out = []
    for i in range(len(audio) // half):
        tracker.feed(audio[i * half : (i + 1) * half])
        out.append(tracker.talking)
    return out[2:]  # skip the first second, while the speech is still filling the window


def test_talking_over_the_fan_is_detected():
    assert np.mean(flagged(over_fan(SPEECH, 0))) > 0.8
    assert np.mean(flagged(over_fan(SPEECH, -6))) > 0.5  # quieter talking: caught often, the hangover covers gaps


def test_fan_alone_is_not_talking():
    assert not any(flagged(synth.fan(30, seed=3)))


def test_faults_are_not_mistaken_for_talking():
    for seed in range(3):
        for fault in (synth.whine, synth.rattle):
            assert not any(flagged(fault(synth.fan(20, seed=seed), **{"seed": seed} if fault is synth.rattle else {}))), fault.__name__


def run(eng, audio):
    half = features.SR // 2
    for i in range(len(audio) // half):
        eng.push(audio[i * half : (i + 1) * half])
        eng.step()


def test_talking_near_the_fan_raises_no_alert(tmp_path):
    for db in (0, -6):
        eng = Engine(data_dir=tmp_path)
        eng.fit_baseline(synth.fan(60, seed=1))
        run(eng, np.concatenate([synth.fan(2, seed=6), over_fan(SPEECH, db, seed=7)]))
        assert eng.alerts.alerts == [], db


def test_talking_can_be_allowed_to_alert(tmp_path):
    eng = Engine(data_dir=tmp_path)
    eng.fit_baseline(synth.fan(60, seed=1))
    eng.ignore_talking = False
    run(eng, np.concatenate([synth.fan(2, seed=6), over_fan(SPEECH, 0, seed=7)]))
    assert eng.alerts.alerts  # proves the test above is quiet because of the speech check, not a weak signal


def test_fault_during_talking_still_alerts_once_talking_stops(tmp_path):
    eng = Engine(data_dir=tmp_path)
    eng.fit_baseline(synth.fan(60, seed=1))
    talk = over_fan(SPEECH[: 4 * features.SR], 0, seed=7)
    run(eng, synth.whine(np.concatenate([synth.fan(2, seed=6), talk, synth.fan(4, seed=8)])))
    assert eng.alerts.alerts
