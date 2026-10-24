from datetime import datetime, timedelta, timezone

from microaware.link.weather import summarize

T0 = datetime(2026, 10, 24, 0, tzinfo=timezone.utc)


def recent(values):
    return [(T0 + timedelta(hours=3 * i), kp) for i, kp in enumerate(values)]


def test_level_comes_from_latest_kp():
    assert summarize(recent([1, 2, 6.33]), predict=None)["level"] == "storm"
    assert summarize(recent([5, 2, 1.67]), predict=None)["level"] == "calm"


def test_forecast_and_routine_plan_when_model_available():
    fake = lambda values, now: [(now + timedelta(hours=3), 5.0), (now + timedelta(hours=6), 2.0)]
    s = summarize(recent([1] * 8), predict=fake, now=T0 + timedelta(hours=22))
    assert [k for _, k in s["forecast"]] == [5.0, 2.0]
    assert s["routine_send_at"] == (T0 + timedelta(hours=27)).isoformat()


def test_no_data_means_calm_and_says_so():
    s = summarize([], predict=None)
    assert s["level"] == "calm" and s["kp"] is None and "unavailable" in s["source"]
