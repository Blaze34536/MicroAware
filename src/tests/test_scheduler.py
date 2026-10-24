from datetime import datetime, timedelta, timezone

from microaware.forecast.scheduler import MAX_WAIT, plan_send, weather_level

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
H3 = timedelta(hours=3)


def fc(*kps):
    return [(NOW + H3 * (i + 1), kp) for i, kp in enumerate(kps)]


def test_critical_and_normal_send_now_even_in_storm():
    for p in ("critical", "normal"):
        assert plan_send(p, NOW, fc(8, 8))["send_at"] == NOW


def test_routine_sends_now_when_next_window_quiet():
    assert plan_send("routine", NOW, fc(2, 7))["send_at"] == NOW


def test_routine_waits_for_first_quiet_window():
    plan = plan_send("routine", NOW, fc(6, 3))
    assert plan["send_at"] == NOW + 2 * H3
    assert plan["reason"]


def test_routine_caps_wait_at_max():
    assert plan_send("routine", NOW, fc(6, 7, 3))["send_at"] == NOW + MAX_WAIT
    assert plan_send("routine", NOW, fc(6, 7))["send_at"] == NOW + MAX_WAIT


def test_routine_with_empty_forecast_sends_now():
    assert plan_send("routine", NOW, [])["send_at"] == NOW


def test_unknown_priority_rejected():
    import pytest
    with pytest.raises(ValueError):
        plan_send("whenever", NOW, [])


def test_weather_level():
    assert weather_level(2) == "calm"
    assert weather_level(3.9, "C5.0") == "calm"
    assert weather_level(4) == "active"
    assert weather_level(5.67) == "active"
    assert weather_level(2, "M1.2") == "active"
    assert weather_level(6) == "storm"
    assert weather_level(1, "X2.1") == "storm"
