import time

from fastapi.testclient import TestClient

from microaware import synth
from microaware.api import create_app
from microaware.engine import Engine


def run(eng, seconds, seed=0):
    for i in range(int(seconds * 2)):
        eng.push(synth.fan(0.5, seed=seed + i))
        eng.step()


def test_baseline_recorded_over_api_then_status_is_nominal(tmp_path):
    eng = Engine(data_dir=tmp_path)
    client = TestClient(create_app(eng))
    assert client.get("/api/status").json()["state"] == "no_baseline"
    client.post("/api/baseline", json={"seconds": 20})
    run(eng, 21)
    deadline = time.time() + 30
    while eng.state == "training" and time.time() < deadline:
        time.sleep(0.1)
    run(eng, 2, seed=1000)
    status = client.get("/api/status").json()
    assert status["state"] == "nominal" and status["threshold"] > 0
    assert (tmp_path / "baseline_fan_a.pkl").exists()


def test_injected_fault_raises_alert_that_can_be_acked(tmp_path):
    eng = Engine(data_dir=tmp_path)
    eng.fit_baseline(synth.fan(60, seed=1))
    client = TestClient(create_app(eng))
    run(eng, 1)
    client.post("/api/sim/inject", json={"fault": "whine", "seconds": 10})
    run(eng, 2, seed=500)
    alerts = client.get("/api/alerts").json()
    assert len(alerts) == 1 and alerts[0]["evidence"]["top_bands"]
    acked = client.post(f"/api/alerts/{alerts[0]['id']}/ack").json()
    assert acked["state"] == "acknowledged"
    assert client.post("/api/alerts/A-9999/ack").status_code == 404


def test_threshold_scale_changes_effective_threshold(tmp_path):
    eng = Engine(data_dir=tmp_path)
    eng.fit_baseline(synth.fan(30, seed=1))
    client = TestClient(create_app(eng))
    base = client.get("/api/status").json()["threshold"]
    client.put("/api/config", json={"threshold_scale": 2.0})
    assert client.get("/api/status").json()["threshold"] == base * 2
