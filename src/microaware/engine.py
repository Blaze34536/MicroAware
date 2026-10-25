"""Shared state: buffers audio, scores the latest window, tracks alerts and baseline recording."""
import pickle
import queue
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import soundfile as sf

from . import explainer, features, isolate, synth, voice
from .alerts import AlertManager
from .detector import Detector
from .labeler import Labeler, simulated_clips
from .link.downlink import render_image
from .speech import SpeechTracker

MACHINE = "fan_a"
TALK_HANGOVER = 1.0  # keep alerts paused this long after talking, to cover gaps between words
TAPE_SECONDS = 30  # audio kept: the last 1 s is scored, 4 s is the evidence image, up to ~6 s is sent to the isolator
ISOLATE_BUDGET = 20_000  # ElevenLabs credits per run (~30 min of talking), so spoken alerts keep theirs
# The isolator always returns some "voice" (10-30% of a plain fan, up to 60% of a whine), so a window only counts
# as talking when leaving the voice out at least halves its score: true for 21 of 23 talking windows, 0 of 45 whines.
VOICED_THRESHOLD = 2.0  # talking windows are scored from what's left, which is noisier
FAULTS = synth.FAULTS


class Engine:
    def __init__(self, data_dir="data", source="none", llm="default", isolator=None):
        self.llm = llm
        # isolator(audio) -> (voice, credits): over-threshold windows are held and checked for talking first
        self.isolator = isolator
        self.isolate_budget, self.isolate_spent = ISOLATE_BUDGET, 0
        self.isolate_off_until = 0  # in samples pushed: after a failure, alert without it for a minute
        self._held = []  # (window end sample, talking) for the current run of over-threshold windows
        self._jobs = queue.Queue()
        self.alert_lock = threading.Lock()  # alerts are updated live and by the isolator worker
        if isolator:
            threading.Thread(target=self._worker, daemon=True).start()
        self.history = deque(maxlen=1200)  # (time, score): 10 min at 2 Hz
        self.abnormal_since = None
        self.on_alert_ready = []  # callbacks(alert, image) once an alert is explained, e.g. the downlink
        self.downlink_sent = 0
        self._images = {}
        self.guard_until = 0.0  # speaker guard: no alerting while our own audio plays
        self.speech = SpeechTracker()
        self.ignore_talking = True  # no alerting while people talk near the mic
        self.talking_until = 0  # in samples pushed, so the hangover is audio time
        self._heard = 0  # samples already given to the speech tracker
        self.data_dir = Path(data_dir)
        self.source = source
        self.lock = threading.Lock()
        self.buffer = np.zeros(TAPE_SECONDS * features.SR, dtype=np.float32)
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
            chunk = FAULTS[self.inject[0]](chunk, t0=self.inject_pos / features.SR)
            self.inject_pos += len(chunk)
        with self.lock:
            self.buffer = np.concatenate([self.buffer, chunk])[-TAPE_SECONDS * features.SR :]
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
        """Fit the fault labeler on the baseline audio, simulated faults mixed into it, and every recorded clip."""
        normal = self.data_dir / f"baseline_{MACHINE}.wav"
        if not normal.exists():
            raise ValueError("Record the normal sound first.")
        normal = sf.read(normal, dtype="float32")[0]
        clips = simulated_clips(normal)
        for f in sorted(self._labels_dir().glob("*.wav")):
            clips.setdefault(f.stem.rsplit("_", 1)[0], []).append(sf.read(f, dtype="float32")[0])
        lab = Labeler.fit(normal, clips)
        self._labeler_path().write_bytes(pickle.dumps(lab))
        self.labeler = lab
        return lab.labels

    def fit_baseline(self, audio):
        det = Detector.fit(audio)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._baseline_path().write_bytes(pickle.dumps(det))
        sf.write(self.data_dir / f"baseline_{MACHINE}.wav", audio, features.SR)  # reused to train the labeler
        self.detector, self.alerts = det, AlertManager(MACHINE)
        self.train_labeler()  # simulated faults on this fan, so alerts get names without recording clips

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
            new = self.buffer[-min(self.pushed - self._heard, len(self.buffer)) :].copy() if self.pushed > self._heard else None
            self._heard = self.pushed
            recent = self.buffer[-4 * features.SR :].copy()
            if self.recording is not None and self.record_progress() >= 1:
                audio, self.recording = np.concatenate(self.recording), None
                if self.record_label:
                    self._save_clip(self.record_label, audio)
                else:
                    self.training = True
                    threading.Thread(target=self._train, args=(audio,), daemon=True).start()
        self.last["mel"] = features.logmel(window).mean(axis=1)
        if new is not None:
            self.speech.feed(new)
            if self.speech.talking:
                self.talking_until = self.pushed + int(TALK_HANGOVER * features.SR)
        det = self.detector
        if det is None or self.training or self.pushed < features.SR:
            self.last.update(score=None, residual=None, top_bands=[])
            return None
        guarded, talk = time.time() < self.guard_until, self.ignore_talking and self.talking()
        score = det.score(window)
        top = [{"band_hz": f"{lo:.0f}-{hi:.0f}", "delta_db": d} for (lo, hi), d in
               ((b["band_hz"], b["delta_db"]) for b in det.top_bands(window))]
        self.last.update(score=score, residual=det.residual(window), top_bands=top)
        self.history.append((time.time(), score))
        alert = None
        # every jump is checked, not just when Silero hears talking: it misses speech a third as loud as a real fan
        if not guarded and self.alerts.state == "nominal" and score > self.threshold and self._can_isolate():
            self._held.append((self.pushed, talk))  # suspicious: let the isolator say how much talking explains
            if self._held[-1][0] - self._held[0][0] + features.SR >= isolate.MIN_SECONDS * features.SR:
                self._flush()
        else:
            if self._held:
                self._flush()
            with self.alert_lock:
                self.alerts.paused = guarded or talk
                alert = self.alerts.update(score, self.threshold, top)
        if self.alerts.state == "nominal":
            self.abnormal_since = None
        elif self.abnormal_since is None:
            self.abnormal_since = time.time()
        if alert:
            self._raised(alert, window, recent)
        return alert

    def _raised(self, alert, window, recent):
        if self.labeler:
            alert["label"], alert["label_conf"] = self.labeler.predict(window)
        self._images[alert["id"]] = render_image(recent)
        threading.Thread(target=self._explain, args=(alert,), daemon=True).start()

    def _can_isolate(self):
        return (self.isolator is not None and self.ignore_talking and self.isolate_spent < self.isolate_budget
                and self.pushed >= self.isolate_off_until)

    def _flush(self):
        """Send the held windows, padded with earlier audio to the isolator's minimum length, to the worker."""
        held, self._held = self._held, []
        with self.lock:
            end = held[-1][0]
            start = max(0, self.pushed - len(self.buffer), min(held[0][0] - features.SR, end - int(isolate.MIN_SECONDS * features.SR)))
            base = self.pushed - len(self.buffer)
            audio = self.buffer[start - base : end - base].copy()
        self._jobs.put((audio, start, held))

    def drain(self):
        """Wait for held windows to be checked (tests)."""
        if self._held:
            self._flush()
        self._jobs.join()

    def _worker(self):
        while True:
            job = self._jobs.get()
            try:
                self._check(*job)
            except Exception as e:
                print(f"Isolator check failed: {e}")
            finally:
                self._jobs.task_done()

    def _check(self, audio, start, held):
        voice = None
        if len(audio) >= 4.6 * features.SR:  # shorter only right after start-up: judge it as is
            try:
                voice, cost = self.isolator(audio)
                self.isolate_spent += cost
            except Exception as e:
                print(f"Voice isolation unavailable ({e}); alerting without it for a minute.")
                self.isolate_off_until = self.pushed + 60 * features.SR
        det = self.detector
        for end, talk in held:
            w = audio[end - features.SR - start : end - start]
            score, voiced, top = det.score(w), False, det.top_bands(w)
            if voice is not None:
                masked, _, masked_top = det.score_masked(w, voice[end - features.SR - start : end - start])
                voiced = masked < score / 2
                if voiced:
                    score, top = masked, masked_top
            elif talk:
                continue  # no isolator: fall back to the local talking pause
            thr = self.threshold * (VOICED_THRESHOLD if voiced else 1)
            top = [{"band_hz": f"{lo:.0f}-{hi:.0f}", "delta_db": b["delta_db"]} for b in top for lo, hi in [b["band_hz"]]]
            with self.alert_lock:
                alert = self.alerts.update(score, thr, top, force=True)
            if alert:
                alert["evidence"]["voice_removed"] = voiced
                self._raised(alert, w, audio[-4 * features.SR :])

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

    def talking(self):
        return self.pushed < self.talking_until

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
            "talking": self.talking(),
            "checking": bool(self._held) or self._jobs.unfinished_tasks > 0,
            "isolator": {"on": self._can_isolate(), "spent": self.isolate_spent, "budget": self.isolate_budget}
            if self.isolator else None,
            "ignore_talking": self.ignore_talking,
            "inject": self.inject[0] if self.inject and time.time() < self.inject[1] else None,
            "alerts": self.alerts.alerts[-20:][::-1],
        }
