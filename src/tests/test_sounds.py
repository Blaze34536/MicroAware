import pytest
from fastapi.testclient import TestClient

from microaware import sounds, synth
from microaware.api import create_app
from microaware.engine import Engine


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return TestClient(create_app(Engine(data_dir=tmp_path_factory.mktemp("d"), llm=None)))


def test_catalog_has_a_fixed_and_broken_sound_for_every_machine(client):
    groups = client.get("/api/sounds").json()
    fan = groups[0]
    assert [s["condition"] for s in fan["sounds"]].count("normal") == 1
    assert sorted(s["fault"] for s in fan["sounds"] if s["condition"] == "broken") == sorted(synth.FAULTS)
    mimii = [g for g in groups if "MIMII" in g["credit"]]
    assert [g["sounds"][0]["id"].split("_")[0] for g in mimii] == ["fan", "pump", "slider", "valve"]
    for g in groups:
        assert {s["condition"] for s in g["sounds"]} == {"normal", "broken"} and g["credit"]
        for s in g["sounds"]:
            r = client.get(s["url"])
            assert r.status_code == 200 and len(r.content) > 10_000, s["url"]


@pytest.mark.parametrize("sound_id,label", [("fan_normal", None)] + [(f"fan_{f}", f) for f in sorted(synth.FAULTS)])
def test_microaware_names_each_library_fan_sound(client, sound_id, label):
    out = client.post(f"/api/sounds/{sound_id}/analyze").json()
    assert out["abnormal"] is (label is not None) and out["label"] == label


def test_other_machines_cant_be_analyzed_without_their_own_baseline(client):
    r = client.post("/api/sounds/pump_abnormal/analyze")
    assert r.status_code == 422 and "baseline" in r.json()["detail"]


def test_unknown_sound_is_404(client):
    assert client.get("/api/sounds/nope.wav").status_code == 404


def test_sounds_page_is_served(client):
    assert "Sounds" in client.get("/sounds").text


def test_alert_fix_endpoint_returns_repair_steps(tmp_path):
    eng = Engine(data_dir=tmp_path, llm=None)
    eng.fit_baseline(sounds.fan_audio()[: 30 * 16000])
    alert = eng.alerts._raise(50.0, 1.5, [])
    alert["label"] = "air_leak"
    out = TestClient(create_app(eng)).get(f"/api/alerts/{alert['id']}/fix").json()
    assert out["steps"] and "leak" in out["summary"].lower()
    assert TestClient(create_app(eng)).get("/api/alerts/A-9999/fix").status_code == 404
