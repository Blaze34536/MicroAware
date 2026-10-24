"""Sends each alert to Earth twice, raw and shielded, over a lossy link, and tracks what arrived."""
import json
import threading
import time

import numpy as np

from .. import features
from .packet import MODES, Receiver, build_message, encode, parse_message

IMAGE_W, IMAGE_H = 96, 72
IMAGE_BYTES = IMAGE_W * IMAGE_H
LEVELS = ["calm", "active", "storm"]
CODE_TO_MODE = {code: name for name, (code, *_) in MODES.items()}


def choose_mode(weather, flare_level, priority):
    """The highest of: weather level, manual flare, priority floor (critical never below active)."""
    flare = "storm" if flare_level >= 10 else "active" if flare_level > 0 else "calm"  # flare sweep: active (4 of 6) drops under 90% delivery from ~15%
    floor = "active" if priority == "critical" else "calm"
    return max(weather, flare, floor, key=LEVELS.index)


def render_image(audio):
    """Spectrogram of recent audio as 96x72 8-bit grayscale, low frequencies at the bottom."""
    db = features.logmel(audio)[::-1]  # (bands, frames), high bands first
    rows = np.linspace(0, db.shape[0] - 1, IMAGE_H)
    cols = np.linspace(0, db.shape[1] - 1, IMAGE_W)
    img = db[np.round(rows).astype(int)][:, np.round(cols).astype(int)]
    img = np.clip((img - (img.max() - 60)) / 60, 0, 1)
    return (img * 255).astype(np.uint8).tobytes()


class SimLink:
    """Software stand-in for the radio: a 'Sun' that wipes out frames during bursts.

    Same timing model as the Sun firmware: each cycle lasts 200-400 ms (random, like real flare
    activity, and so it can't phase-lock with the interleaver), and the burst is duty x cycle."""

    name = "simulated"

    def __init__(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.duty = 0
        self.t = 0.0  # virtual airtime clock
        self.cycle_end, self.burst_end = 0.0, 0.0
        self.on_frame = lambda frame: None

    def set_duty(self, percent, seconds=None):
        self.duty = percent

    def _lost(self):
        while self.t >= self.cycle_end:
            start = self.cycle_end
            self.cycle_end = start + self.rng.uniform(0.2, 0.4)
            self.burst_end = start + self.duty / 100 * (self.cycle_end - start)
        return self.t < self.burst_end

    def transmit_mask(self, n, gap):
        mask = []
        for _ in range(n):
            mask.append(not self._lost())
            self.t += gap
        return mask

    def transmit(self, frames, gap):
        for frame, ok in zip(frames, self.transmit_mask(len(frames), gap)):
            if ok:
                self.on_frame(frame)


class Downlink:
    def __init__(self, link, weather=None):
        self.link = link
        self.link.on_frame = self.receive
        self.weather = weather or {"level": "calm", "kp": None, "source": "not polled"}
        self.receiver = Receiver()
        self.records = []
        self.flare_level, self.flare_until = 0, 0.0
        self.lock = threading.Lock()
        self._next_id = 1

    def receive(self, frame):
        with self.lock:
            self.receiver.feed(frame)

    def set_flare(self, level, seconds):
        self.flare_level, self.flare_until = level, time.time() + seconds
        self.link.set_duty(level, seconds=seconds)

    def flare(self):
        if self.flare_level and time.time() >= self.flare_until:
            self.flare_level = 0
            self.link.set_duty(0)
        return self.flare_level

    def send_alert(self, alert, image, priority=None):
        priority = priority or ("critical" if alert.get("severity") == "critical" else "normal")
        mode = choose_mode(self.weather["level"], self.flare(), priority)
        body = json.dumps({k: v for k, v in alert.items() if k != "audio"}, separators=(",", ":")).encode()
        msg = build_message(body, image[:IMAGE_BYTES].ljust(IMAGE_BYTES, b"\0"))
        with self.lock:
            msg_id, self._next_id = self._next_id, (self._next_id + 1) % 0x10000 or 1
        raw, shield = encode(msg, msg_id, "raw", priority), encode(msg, msg_id, mode, priority)
        # alternate raw and shielded frames so both copies face the same storm
        order = [f for pair in zip(raw, shield) for f in pair] + raw[len(shield):] + shield[len(raw):]
        gap = MODES[mode][3]
        record = {"msg_id": msg_id, "alert_id": alert["id"], "mode": mode, "priority": priority,
                  "sent_at": time.time(), "link": self.link.name, "flare": self.flare_level,
                  "weather": dict(self.weather), "frames_sent": {"raw": len(raw), "shield": len(shield)},
                  "overhead_pct": round(100 * (len(shield) / len(raw) - 1)), "airtime_s": round(len(order) * gap, 2)}
        self.records.append(record)
        self.link.transmit(order, gap)
        return self.status(record)

    def _copy(self, record, mode):
        rec = self.receiver.messages.get((record["msg_id"], MODES[mode][0]))
        sent = record["frames_sent"]["raw" if mode == "raw" else "shield"]
        if rec is None:
            return {"delivered": False, "frames": 0, "sent": sent, "loss_pct": 100.0}
        return {"delivered": rec.delivered, "sent": sent, "loss_pct": round(100 * (1 - rec.frames / sent), 1)} | rec.stats()

    def status(self, record):
        return record | {"raw": self._copy(record, "raw"), "shield": self._copy(record, record["mode"])}

    def delivery(self, alert_id):
        """Did the latest downlink of this alert arrive intact?"""
        for record in reversed(self.records):
            if record["alert_id"] == alert_id:
                s = self.status(record)
                return {"alert_id": alert_id, "delivered": s["shield"]["delivered"], "raw_delivered": s["raw"]["delivered"],
                        "mode": s["mode"], "msg_id": s["msg_id"], "rebuilt_packets": s["shield"].get("rebuilt", 0),
                        "loss_pct": s["shield"]["loss_pct"]}
        return None

    def earth_view(self, msg_id):
        """What Earth has for one message: decoded alert (if intact) and the image, lost parts black."""
        record = next(r for r in self.records if r["msg_id"] == msg_id)
        out = self.status(record)
        for copy, mode in (("raw", "raw"), ("shield", record["mode"])):
            rec = self.receiver.messages.get((msg_id, MODES[mode][0]))
            msg = rec.message() if rec else b""
            alert = None
            if rec and rec.delivered:
                alert = json.loads(parse_message(msg)[0])
            image = msg[-4 - IMAGE_BYTES : -4] if len(msg) >= IMAGE_BYTES + 4 else bytes(IMAGE_BYTES)
            out[copy] = out[copy] | {"alert": alert, "image": list(image)}
        return out

    def totals(self, seconds=60):
        """Measured link numbers over recent messages, for the status bar and voice agent."""
        recent = [self.status(r) for r in self.records if r["sent_at"] >= time.time() - seconds]
        sent = sum(r["frames_sent"]["raw"] + r["frames_sent"]["shield"] for r in recent)
        lost = sum(r[c]["sent"] * r[c]["loss_pct"] / 100 for r in recent for c in ("raw", "shield"))
        return {"messages": len(recent), "frames_sent": sent, "loss_pct": round(100 * lost / sent, 1) if sent else None,
                "shield_delivered": sum(r["shield"]["delivered"] for r in recent),
                "raw_delivered": sum(r["raw"]["delivered"] for r in recent),
                "rebuilt": sum(r["shield"].get("rebuilt", 0) for r in recent)}
