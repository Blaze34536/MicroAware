"""Debounced machine-anomaly alerts, in the shape Storm Shield will transmit."""
from datetime import datetime, timezone

RAISE_AFTER = 3  # consecutive windows over threshold (1.5 s)
CLEAR_AFTER = 6  # consecutive windows under CLEAR_RATIO * threshold (3 s)
CLEAR_RATIO = 0.8


class AlertManager:
    def __init__(self, source):
        self.source = source
        self.state = "nominal"
        self.paused = False  # speaker guard: our own audio is playing
        self.alerts = []
        self._over = self._under = 0

    def update(self, score, threshold, top_bands):
        """Feed one window's score; returns a new alert dict when one is raised."""
        if self.paused:
            return None
        self._over = self._over + 1 if score > threshold else 0
        self._under = self._under + 1 if score < CLEAR_RATIO * threshold else 0
        if self.state == "nominal" and self._over >= RAISE_AFTER:
            self.state = "abnormal"
            return self._raise(score, threshold, top_bands)
        if self.state == "abnormal" and self._under >= CLEAR_AFTER:
            self.state = "nominal"
            for a in self.alerts:
                if a["state"] == "active":
                    a["state"] = "cleared"
        return None

    def _raise(self, score, threshold, top_bands):
        alert = {
            "id": f"A-{len(self.alerts) + 1:04d}",
            "t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": self.source,
            "kind": "machine_anomaly",
            "severity": "warning",
            "label": None,
            "label_conf": None,
            "evidence": {"score": round(score, 2), "threshold": round(threshold, 2), "top_bands": top_bands},
            "explanation": None,
            "state": "active",
        }
        self.alerts.append(alert)
        return alert

    def get(self, alert_id):
        return next((a for a in self.alerts if a["id"] == alert_id), None)

    def ack(self, alert_id):
        alert = self.get(alert_id)
        if alert:
            alert["state"] = "acknowledged"
        return alert
