from microaware.alerts import AlertManager


def feed(mgr, scores, thr=1.0):
    return [mgr.update(s, thr, top_bands=[]) for s in scores]


def test_alert_needs_three_consecutive_windows_over_threshold():
    mgr = AlertManager("fan_a")
    assert feed(mgr, [5, 5, 0.1, 5, 5]) == [None] * 5
    assert mgr.state == "nominal"
    alert = feed(mgr, [5])[0]
    assert alert["id"] == "A-0001" and alert["kind"] == "machine_anomaly"
    assert mgr.state == "abnormal"


def test_clears_after_six_windows_under_80_percent_of_threshold():
    mgr = AlertManager("fan_a")
    feed(mgr, [5, 5, 5])
    feed(mgr, [0.1] * 5 + [0.9])  # 0.9 is under threshold but not under 0.8x
    assert mgr.state == "abnormal"
    feed(mgr, [0.1] * 6)
    assert mgr.state == "nominal"


def test_paused_windows_do_not_count():
    mgr = AlertManager("fan_a")
    feed(mgr, [5, 5])
    mgr.paused = True
    feed(mgr, [5] * 10)
    assert mgr.state == "nominal"
    mgr.paused = False
    assert feed(mgr, [5])[0] is not None


def test_ack_marks_alert_acknowledged():
    mgr = AlertManager("fan_a")
    alert = feed(mgr, [5, 5, 5])[-1]
    assert mgr.ack(alert["id"])["state"] == "acknowledged"
    assert mgr.ack("A-9999") is None
