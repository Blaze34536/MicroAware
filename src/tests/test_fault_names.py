"""Fault naming trained on simulated faults mixed into the normal sound, checked on fan audio it never saw."""
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from microaware import features, synth
from microaware.engine import Engine
from microaware.labeler import Labeler, simulated_clips

FAN = sf.read(Path(__file__).parents[1] / "static" / "sounds" / "fan_normal.ogg", dtype="float32")[0]
TRAIN, TEST = FAN[: 30 * features.SR], FAN[30 * features.SR :]


@pytest.fixture(scope="module")
def lab():
    return Labeler.fit(TRAIN, simulated_clips(TRAIN))


@pytest.mark.parametrize("label", sorted(synth.FAULTS))
def test_names_each_simulated_fault_on_unseen_fan_audio(lab, label):
    preds = [lab.predict(w)[0] for w in features.windows(synth.FAULTS[label](TEST, t0=3.7))]
    assert preds.count(label) >= 0.8 * len(preds), (label, preds)


def test_unseen_normal_fan_gets_no_fault_name(lab):
    preds = [lab.predict(w)[0] for w in features.windows(TEST)]
    assert preds.count(None) >= 0.9 * len(preds)


def test_recording_a_baseline_also_trains_fault_names(tmp_path):
    eng = Engine(data_dir=tmp_path, llm=None)
    eng.fit_baseline(TRAIN)
    assert sorted(eng.labeler.labels) == sorted(synth.FAULTS)
    assert (tmp_path / "labeler_fan_a.pkl").exists()


def test_simulated_fault_alert_is_named(tmp_path):
    eng = Engine(data_dir=tmp_path, llm=None)
    eng.fit_baseline(TRAIN)
    eng.inject, eng.inject_pos = ("air_leak", float("inf")), 0
    half = features.SR // 2
    for i in range(8):
        eng.push(TEST[i * half : (i + 1) * half])
        eng.step()
    assert eng.alerts.alerts and eng.alerts.alerts[0]["label"] == "air_leak"
