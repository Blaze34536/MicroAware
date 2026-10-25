"""The sound library: a fixed and a broken sound for each machine, and MicroAware's verdict on the fan ones."""
import io
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from . import features, synth
from .detector import Detector
from .labeler import Labeler, simulated_clips

STATIC = Path(__file__).resolve().parent.parent / "static" / "sounds"
TRAIN_SECONDS = 30  # the library model learns from the first 30 s; the clips come from the rest
CLIP = slice(32 * features.SR, 42 * features.SR)
FAULT_TITLES = {
    "imbalance": "Imbalance: tape flag on a blade",
    "bearing": "Worn bearing: high whine",
    "loose_mount": "Loose mount: rattle",
    "air_leak": "Air leak: hiss",
}
MIMII = {  # the dataset says which faults each machine had, not which one each clip has
    "fan": ("Industrial fan", "unbalanced, voltage change or clogging"),
    "pump": ("Water pump", "leakage, contamination or clogging"),
    "slider": ("Slide rail", "rail damage, loose belt or no grease"),
    "valve": ("Solenoid valve", "contamination"),
}
WWS = ('Recorded ventilation fan: "WWS Ventilationfan.ogg" by Work With Sounds, CC BY 4.0. '
       "The broken sounds are MicroAware's simulated faults mixed into it")
MIMII_CREDIT = "MIMII dataset (Purohit et al., Hitachi, 2019), CC BY-SA 4.0, id_00 at 6 dB"


@lru_cache(maxsize=1)
def fan_audio():
    return sf.read(STATIC / "fan_normal.ogg", dtype="float32")[0]


def catalog():
    fan = [{"id": "fan_normal", "condition": "normal", "fault": None, "title": "Running normally",
            "url": "/static/sounds/fan_normal.ogg"}]
    fan += [{"id": f"fan_{f}", "condition": "broken", "fault": f, "title": t, "url": f"/api/sounds/fan_{f}.wav"}
            for f, t in FAULT_TITLES.items()]
    groups = [{"machine": "Habitat fan", "credit": WWS, "analyze": True, "sounds": fan}]
    for m, (name, faults) in MIMII.items():
        groups.append({"machine": name, "credit": MIMII_CREDIT, "analyze": False, "sounds": [
            {"id": f"{m}_normal", "condition": "normal", "fault": None, "title": "Running normally",
             "url": f"/static/sounds/mimii/{m}_normal.ogg"},
            {"id": f"{m}_abnormal", "condition": "broken", "fault": None, "title": f"Broken: {faults}",
             "url": f"/static/sounds/mimii/{m}_abnormal.ogg"}]})
    return groups


def clip(sound_id):
    """10 s of the fan from past the training part, with the named fault mixed in. KeyError if not a fan sound."""
    fault = sound_id.removeprefix("fan_")
    audio = fan_audio()[CLIP]
    return audio if fault == "normal" else synth.FAULTS[fault](audio, t0=CLIP.start / features.SR)


def wav(sound_id):
    buf = io.BytesIO()
    sf.write(buf, clip(sound_id), features.SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


_lock = threading.Lock()


@lru_cache(maxsize=1)
def _model():
    train = fan_audio()[: TRAIN_SECONDS * features.SR]
    return Detector.fit(train), Labeler.fit(train, simulated_clips(train))


def analyze(sound_id):
    """What MicroAware hears in a library fan sound, with a model trained on the first 30 s of that fan."""
    audio = clip(sound_id)
    with _lock:  # the first call trains (~5 s); later ones reuse it
        det, lab = _model()
    wins = list(features.windows(audio))
    scores = [det.score(w) for w in wins]
    abnormal = float(np.median(scores)) > det.threshold
    names = [lab.predict(w) for w in wins] if abnormal else []
    labels = [n for n, _ in names]
    label = max(set(labels), key=labels.count) if labels else None
    conf = float(np.mean([c for n, c in names if n == label])) if label else None
    return {"abnormal": abnormal, "score": round(float(np.median(scores)), 2), "threshold": round(det.threshold, 2),
            "label": label, "confidence": round(conf, 2) if conf else None,
            "windows_named": round(labels.count(label) / len(wins), 2) if label else 0}
