import time

from fastapi.testclient import TestClient

from microaware import synth
from microaware.api import create_app
from microaware.engine import Engine


def run(eng, seconds, seed=0):
    """Feed continuous fan audio in 0.5 s chunks, analyzing after each, like the live loop does."""
    audio = synth.fan(seconds, seed=seed)
    half = len(audio) // int(seconds * 2)
    for i in range(int(seconds * 2)):
        eng.push(audio[i * half : (i + 1) * half])
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


def test_speaker_guard_holds_off_alerts_while_our_audio_plays(tmp_path):
    eng = Engine(data_dir=tmp_path)
    eng.fit_baseline(synth.fan(60, seed=1))
    client = TestClient(create_app(eng))
    client.post("/api/guard", json={"playing": True, "seconds": 30})
    client.post("/api/sim/inject", json={"fault": "whine", "seconds": 30})
    run(eng, 3, seed=500)
    assert client.get("/api/alerts").json() == []
    client.post("/api/guard", json={"playing": False})
    time.sleep(0.6)
    run(eng, 2, seed=900)
    assert len(client.get("/api/alerts").json()) == 1


def test_new_alert_gets_explained(tmp_path):
    eng = Engine(data_dir=tmp_path, llm=None)
    eng.fit_baseline(synth.fan(60, seed=1))
    client = TestClient(create_app(eng))
    client.post("/api/sim/inject", json={"fault": "whine", "seconds": 10})
    run(eng, 2, seed=500)
    deadline = time.time() + 5
    while time.time() < deadline and not client.get("/api/alerts").json()[0]["explanation"]:
        time.sleep(0.05)
    assert client.get("/api/alerts").json()[0]["explanation"]["source"] == "canned"


def test_recorded_fault_clips_train_a_labeler_that_names_alerts(tmp_path):
    eng = Engine(data_dir=tmp_path, llm=None)
    client = TestClient(create_app(eng))
    client.post("/api/baseline", json={"seconds": 20})
    run(eng, 21)
    while eng.state == "training":
        time.sleep(0.1)
    client.post("/api/sim/inject", json={"fault": "whine", "seconds": 30})
    client.post("/api/labels/record", json={"label": "bearing", "seconds": 10})
    run(eng, 11, seed=200)
    assert client.get("/api/labels").json() == {"bearing": 1}
    assert client.post("/api/labeler/train").json()["labels"] == ["bearing"]
    eng.alerts = type(eng.alerts)("fan_a")  # fresh alert state; the fault is still being injected
    run(eng, 2, seed=700)
    assert client.get("/api/alerts").json()[0]["label"] == "bearing"


def test_history_reports_rising_trend_and_abnormal_since(tmp_path):
    eng = Engine(data_dir=tmp_path, llm=None)
    eng.fit_baseline(synth.fan(60, seed=1))
    client = TestClient(create_app(eng))
    run(eng, 5)
    h = client.get("/api/history", params={"minutes": 10}).json()
    assert h["trend"] == "flat" and h["abnormal_since"] is None and len(h["scores"]) >= 9
    client.post("/api/sim/inject", json={"fault": "whine", "seconds": 30})
    run(eng, 5, seed=300)
    h = client.get("/api/history").json()
    assert h["trend"] == "rising" and h["abnormal_since"] is not None


def test_voice_config_exposes_only_the_agent_id(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_123")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret")
    body = TestClient(create_app(Engine(data_dir=tmp_path))).get("/api/voice/config").json()
    assert body == {"agent_id": "agent_123"}
