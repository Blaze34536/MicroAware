from microaware import synth
from microaware.features import windows
from microaware.labeler import Labeler

NORMAL = synth.fan(30, seed=1)
CLIPS = {"bearing": [synth.whine(synth.fan(15, seed=2))], "loose_mount": [synth.rattle(synth.fan(15, seed=3), seed=3)]}


def test_names_known_faults():
    lab = Labeler.fit(NORMAL, CLIPS)
    for label, make in (("bearing", lambda x: synth.whine(x)), ("loose_mount", lambda x: synth.rattle(x, seed=9))):
        preds = [lab.predict(w)[0] for w in windows(make(synth.fan(5, seed=40)))]
        assert preds.count(label) >= 0.8 * len(preds), (label, preds)


def test_normal_sound_is_not_given_a_fault_label():
    lab = Labeler.fit(NORMAL, CLIPS)
    assert all(lab.predict(w)[0] is None for w in windows(synth.fan(5, seed=50)))


def test_low_confidence_reports_unknown():
    lab = Labeler.fit(NORMAL, CLIPS)
    lab.min_conf = 1.01
    assert lab.predict(next(windows(synth.whine(synth.fan(2, seed=60)))))[0] is None
