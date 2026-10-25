"""Live NOAA space weather -> link protection level, plus the Kp forecast for timing routine traffic."""
import threading
import time
from datetime import datetime, timezone

from ..forecast import kp_data, kp_model
from ..forecast.scheduler import plan_send, weather_level

POLL_S = 60


def summarize(recent, predict, now=None):
    """recent: [(window start, kp)] oldest first; predict: kp_model.predict-like callable or None."""
    now = now or datetime.now(timezone.utc)
    if not recent:
        return {"level": "calm", "kp": None, "source": "NOAA unavailable", "forecast": [], "routine_send_at": None}
    t_last, kp = recent[-1]
    forecast = []
    if predict and len(recent) >= 8:
        forecast = predict([k for _, k in recent[-8:]], t_last)
    plan = plan_send("routine", now, forecast)
    return {
        "level": weather_level(kp),
        "kp": kp,
        "kp_time": t_last.isoformat(),
        "source": "NOAA SWPC planetary K-index",
        "forecast": [(t.isoformat(), round(k, 2)) for t, k in forecast],
        "routine_send_at": plan["send_at"].isoformat(),
        "routine_reason": plan["reason"],
    }


def start_polling(downlink):
    """Refresh downlink.weather every minute; on failure keep the last good reading."""
    try:
        models = kp_model.load()
        predict = lambda values, now: kp_model.predict(values, now, models)
    except FileNotFoundError:
        print("No Kp model yet (run: python -m microaware.forecast train); using live Kp only.")
        predict = None

    def loop():
        while True:
            try:
                downlink.weather = summarize(kp_data.fetch_recent(), predict)
            except Exception as e:
                if downlink.weather.get("kp") is None:
                    downlink.weather = summarize([], None)
                print(f"NOAA poll failed ({e}); keeping the last reading.")
            time.sleep(POLL_S)

    threading.Thread(target=loop, daemon=True).start()
