"""Decide when to send a message given a Kp forecast. Pure functions, no network."""
from datetime import timedelta

QUIET_KP = 4.0
MAX_WAIT = timedelta(hours=6)


def plan_send(priority, now, forecast):
    """forecast: list of (time, kp) for upcoming 3-hour windows, earliest first."""
    if priority in ("critical", "normal"):
        return {"send_at": now, "reason": f"{priority} traffic never waits"}
    if priority != "routine":
        raise ValueError(f"unknown priority: {priority!r}")
    if not forecast:
        return {"send_at": now, "reason": "no forecast available, sending now"}
    if forecast[0][1] < QUIET_KP:
        return {"send_at": now, "reason": f"next window quiet (Kp {forecast[0][1]:.1f})"}
    for t, kp in forecast:
        if kp < QUIET_KP:
            if t - now <= MAX_WAIT:
                return {"send_at": t, "reason": f"waiting for quiet window (Kp {kp:.1f})"}
            break
    return {"send_at": now + MAX_WAIT, "reason": "no quiet window within 6 h, sending at max wait"}


def weather_level(kp, xray_class=None):
    """xray_class like 'C5.0', 'M1.2', 'X2.1' (only the letter matters)."""
    flare = (xray_class or "").strip().upper()[:1]
    if kp >= 6 or flare == "X":
        return "storm"
    if kp >= 4 or flare == "M":
        return "active"
    return "calm"
