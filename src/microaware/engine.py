"""Shared state: buffers audio, scores the latest window, tracks alerts and baseline recording."""
import pickle
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import soundfile as sf

from . import explainer, features, synth, voice
from .alerts import AlertManager
from .detector import Detector
from .labeler import Labeler
from .link.downlink import render_image

MACHINE = "fan_a"
FAULTS = {"whine": synth.whine, "rattle": synth.rattle}


class Engine:
    def __init__(self, data_dir="data", source="none", llm="default"):
        self.llm = llm
        self.history = deque(maxlen=1200)  # (time, score): 10 min at 2 Hz
        self.abnormal_since = None
        self.on_alert_ready = []  # callbacks(alert, image) once an alert is explained, e.g. the downlink
        self.downlink_sent = 0
        self._images = {}
        self.guard_until = 0.0  # speaker guard: no alerting while our own audio plays
        self.data_dir = Path(data_dir)
        self.source = source
        self.lock = threading.Lock()
        self.buffer = np.zeros(4 * features.SR, dtype=np.float32)  # latest 4 s: last 1 s is scored, all 4 s is the evidence image
        self.pushed = 0  # samples received; scoring waits for a full real second
        self.recording = None  # list of chunks while recording a baseline
        self.record_seconds = 0
        self.record_label = None  # None records the normal baseline; a name records a fault clip
        self.training = False
        self.threshold_scale = 1.0
        self.inject = None  # (fault name, end time)
        self.inject_pos = 0  # samples since the injection started
        self.alerts = AlertManager(MACHINE)
        self.last = {"score": None, "mel": None, "residual": None, "top_bands": []}
        self.detector = self._load(self._baseline_path())
        self.labeler = self._load(self._labeler_path())

    @staticmethod
    def _load(path):
        return pickle.loads(path.read_bytes()) if path.exists() else None

    def _baseline_path(self):
        return self.data_dir / f"baseline_{MACHINE}.pkl"

    def _labeler_path(self):
        return self.data_dir / f"labeler_{MACHINE}.pkl"

    def _labels_dir(self):
        return self.data_dir / "labels"

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
        if self.inject and time.time() < self.inject[1]:
            # mixed in at the input so recordings and scoring both hear the simulated fault
            name, pos = self.inject[0], self.inject_pos
            chunk = FAULTS[name](chunk, **({"t0": pos / features.SR} if name == "whine" else {"seed": pos}))
            self.inject_pos += len(chunk)
        with self.lock:
            self.buffer = np.concatenate([self.buffer, chunk])[-4 * features.SR :]
            self.pushed += len(chunk)
            if self.recording is not None:
                self.recording.append(chunk)

    def start_baseline(self, seconds, label=None):
        with self.lock:
            self.recording, self.record_seconds, self.record_label = [], seconds, label

    def label_counts(self):
        counts = {}
        for f in sorted(self._labels_dir().glob("*.wav")):
            label = f.stem.rsplit("_", 1)[0]
            counts[label] = counts.get(label, 0) + 1
        return counts

    def _save_clip(self, label, audio):
        self._labels_dir().mkdir(parents=True, exist_ok=True)
        n = self.label_counts().get(label, 0) + 1
        sf.write(self._labels_dir() / f"{label}_{n}.wav", audio, features.SR)

    def train_labeler(self):
        """Fit the fault labeler on the saved baseline audio plus every recorded clip."""
        normal = self.data_dir / f"baseline_{MACHINE}.wav"
        if not normal.exists():
            raise ValueError("Record the normal sound first.")
        clips = {}
        for f in sorted(self._labels_dir().glob("*.wav")):
            clips.setdefault(f.stem.rsplit("_", 1)[0], []).append(sf.read(f, dtype="float32")[0])
        if not clips:
            raise ValueError("Record at least one fault clip first.")
        lab = Labeler.fit(sf.read(normal, dtype="float32")[0], clips)
        self._labeler_path().write_bytes(pickle.dumps(lab))
        self.labeler = lab
        return lab.labels

    def fit_baseline(self, audio):
        det = Detector.fit(audio)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._baseline_path().write_bytes(pickle.dumps(det))
        sf.write(self.data_dir / f"baseline_{MACHINE}.wav", audio, features.SR)  # reused to train the labeler
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
            window = self.buffer[-features.SR :].copy()
            recent = self.buffer.copy()
            if self.recording is not None and self.record_progress() >= 1:
                audio, self.recording = np.concatenate(self.recording), None
                if self.record_label:
                    self._save_clip(self.record_label, audio)
                else:
                    self.training = True
                    threading.Thread(target=self._train, args=(audio,), daemon=True).start()
        self.last["mel"] = features.logmel(window).mean(axis=1)
        det = self.detector
        if det is None or self.training or self.pushed < features.SR:
            self.last.update(score=None, residual=None, top_bands=[])
            return None
        self.alerts.paused = time.time() < self.guard_until
        score = det.score(window)
        top = [{"band_hz": f"{lo:.0f}-{hi:.0f}", "delta_db": d} for (lo, hi), d in
               ((b["band_hz"], b["delta_db"]) for b in det.top_bands(window))]
        self.last.update(score=score, residual=det.residual(window), top_bands=top)
        self.history.append((time.time(), score))
        alert = self.alerts.update(score, self.threshold, top)
        if self.alerts.state == "nominal":
            self.abnormal_since = None
        elif self.abnormal_since is None:
            self.abnormal_since = time.time()
        if alert:
            if self.labeler:
                alert["label"], alert["label_conf"] = self.labeler.predict(window)
            self._images[alert["id"]] = render_image(recent)
            threading.Thread(target=self._explain, args=(alert,), daemon=True).start()
        return alert

    def _explain(self, alert):
        expl = explainer.explain(alert, llm=self.llm)
        if voice.synthesize(expl["spoken"], alert["severity"], self.voice_path(alert["id"])):
            alert["audio"] = f"/api/voice/alert/{alert['id']}.mp3"
        alert["explanation"] = expl  # set last: the dashboard speaks once this appears
        for callback in self.on_alert_ready:
            try:
                callback(alert, self._images[alert["id"]])
                self.downlink_sent += 1
            except Exception as e:
                print(f"Alert {alert['id']} callback failed: {e}")

    def image(self, alert_id):
        return self._images.get(alert_id)

    def history_summary(self, minutes=10):
        """Scores over the last `minutes` plus a plain trend, for the voice agent's 'is it getting worse?'."""
        since = time.time() - minutes * 60
        pts = [(t, sc) for t, sc in self.history if t >= since]
        recent, before = [sc for _, sc in pts[-10:]], [sc for _, sc in pts[-20:-10]]
        trend = "flat"
        if recent and before:
            ratio = float(np.median(recent) / max(np.median(before), 1e-9))
            trend = "rising" if ratio > 1.5 else "falling" if ratio < 1 / 1.5 else "flat"
        return {
            "minutes": minutes,
            "state": self.state,
            "threshold": self.threshold,
            "trend": trend,
            "abnormal_since": self.abnormal_since,
            "abnormal_for_s": round(time.time() - self.abnormal_since) if self.abnormal_since else None,
            "scores": [[round(t, 1), round(sc, 3)] for t, sc in pts[::max(1, len(pts) // 120)]],  # at most ~120 points
        }

    def voice_path(self, alert_id):
        return self.data_dir / "voice" / f"{alert_id}.mp3"

    def guard(self, playing, seconds=30):
        self.guard_until = time.time() + (seconds if playing else 0.5)

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
            "record_label": self.record_label if self.recording is not None else None,
            "labels": self.label_counts(),
            "labeler": self.labeler.labels if self.labeler else None,
            "guarded": time.time() < self.guard_until,
            "inject": self.inject[0] if self.inject and time.time() < self.inject[1] else None,
            "alerts": self.alerts.alerts[-20:][::-1],
        }
