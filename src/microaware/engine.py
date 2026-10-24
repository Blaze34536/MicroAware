"""Shared state: buffers audio, scores the latest window, tracks alerts and baseline recording."""
import pickle
import threading
import time
from pathlib import Path

import numpy as np

from . import features, synth
from .alerts import AlertManager
from .detector import Detector

MACHINE = "fan_a"
FAULTS = {"whine": synth.whine, "rattle": synth.rattle}


class Engine:
    def __init__(self, data_dir="data", source="none"):
        self.data_dir = Path(data_dir)
        self.source = source
        self.lock = threading.Lock()
        self.buffer = np.zeros(features.SR, dtype=np.float32)  # always the latest 1 s
        self.recording = None  # list of chunks while recording a baseline
        self.record_seconds = 0
        self.training = False
        self.threshold_scale = 1.0
        self.inject = None  # (fault name, end time)
        self.alerts = AlertManager(MACHINE)
        self.last = {"score": None, "mel": None, "residual": None, "top_bands": []}
        self.detector = None
        path = self._baseline_path()
        if path.exists():
            self.detector = pickle.loads(path.read_bytes())

    def _baseline_path(self):
        return self.data_dir / f"baseline_{MACHINE}.pkl"

    @property
    def state(self):
        if self.recording is not None:
            return "recording"
        if self.training:
            return "training"
        if self.detector is None:
            return "no_baseline"
        return self.alerts.state

    @property
    def threshold(self):
        return self.detector.threshold * self.threshold_scale if self.detector else None

    def push(self, chunk):
        with self.lock:
            self.buffer = np.concatenate([self.buffer, chunk])[-features.SR :]
            if self.recording is not None:
                self.recording.append(chunk)

    def start_baseline(self, seconds):
        with self.lock:
            self.recording, self.record_seconds = [], seconds

    def fit_baseline(self, audio):
        det = Detector.fit(audio)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._baseline_path().write_bytes(pickle.dumps(det))
        self.detector, self.alerts = det, AlertManager(MACHINE)

    def _train(self, audio):
        try:
            self.fit_baseline(audio)
        finally:
            self.training = False

    def record_progress(self):
        if self.recording is None:
            return None
        return min(1.0, sum(map(len, self.recording)) / features.SR / self.record_seconds)

    def step(self):
        """Analyze the latest 1 s window. Called every 0.5 s."""
        with self.lock:
            window = self.buffer.copy()
            if self.recording is not None and self.record_progress() >= 1:
                audio, self.recording = np.concatenate(self.recording), None
                self.training = True
                threading.Thread(target=self._train, args=(audio,), daemon=True).start()
        if self.inject and time.time() < self.inject[1]:
            window = FAULTS[self.inject[0]](window, **({"seed": int(time.time() * 2)} if self.inject[0] == "rattle" else {}))
        self.last["mel"] = features.logmel(window).mean(axis=1)
        det = self.detector
        if det is None or self.training:
            self.last.update(score=None, residual=None, top_bands=[])
            return None
        score = det.score(window)
        top = [{"band_hz": f"{lo:.0f}-{hi:.0f}", "delta_db": d} for (lo, hi), d in
               ((b["band_hz"], b["delta_db"]) for b in det.top_bands(window))]
        self.last.update(score=score, residual=det.residual(window), top_bands=top)
        return self.alerts.update(score, self.threshold, top)

    def snapshot(self):
        r = lambda a: None if a is None else [round(float(v), 1) for v in a]
        return {
            "type": "tick",
            "t": time.time(),
            "source": self.source,
            "machine": MACHINE,
            "state": self.state,
            "score": None if self.last["score"] is None else round(self.last["score"], 3),
            "threshold": self.threshold,
            "threshold_scale": self.threshold_scale,
            "mel": r(self.last["mel"]),
            "residual": r(self.last["residual"]),
            "top_bands": self.last["top_bands"],
            "record_progress": self.record_progress(),
            "inject": self.inject[0] if self.inject and time.time() < self.inject[1] else None,
            "alerts": self.alerts.alerts[-20:][::-1],
        }
