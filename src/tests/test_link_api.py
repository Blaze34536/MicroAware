import time

from fastapi.testclient import TestClient

from microaware import synth
from microaware.api import create_app
from microaware.engine import Engine
from microaware.link.downlink import Downlink, SimLink

from test_api import run


def setup(tmp_path):
    eng = Engine(data_dir=tmp_path, llm=None)
    eng.fit_baseline(synth.fan(60, seed=1))
    dl = Downlink(SimLink(seed=5))
    eng.on_alert_ready.append(dl.send_alert)
    return eng, dl, TestClient(create_app(eng, dl))


def raise_alert(eng, client):
    client.post("/api/sim/inject", json={"fault": "bearing", "seconds": 10})
    run(eng, 4, seed=500)
    deadline = time.time() + 5
    while time.time() < deadline and not eng.downlink_sent:
        time.sleep(0.05)
    return client.get("/api/alerts").json()[0]["id"]


def test_explained_alert_is_downlinked_and_delivery_is_reported(tmp_path):
    eng, dl, client = setup(tmp_path)
    alert_id = raise_alert(eng, client)
    d = client.get(f"/api/link/delivery/{alert_id}").json()
    assert d["delivered"] is True and d["mode"] == "calm"
    status = client.get("/api/link/status").json()
    assert status["link"] == "simulated" and status["last_minute"]["messages"] == 1


def test_flare_switches_mode_and_resend_goes_out_in_storm(tmp_path):
    eng, dl, client = setup(tmp_path)
    alert_id = raise_alert(eng, client)
    client.post("/api/link/flare", json={"level": 40, "seconds": 30})
    assert client.get("/api/link/status").json()["mode"] == "storm"
    rec = client.post(f"/api/link/send/{alert_id}").json()
    assert rec["mode"] == "storm" and rec["shield"]["delivered"] and not rec["raw"]["delivered"]


def test_earth_page_and_message_images(tmp_path):
    eng, dl, client = setup(tmp_path)
    raise_alert(eng, client)
    assert client.get("/earth").status_code == 200
    msgs = client.get("/api/link/messages").json()
    view = client.get(f"/api/link/messages/{msgs[0]['msg_id']}").json()
    assert len(view["shield"]["image"]) == 96 * 72 and view["shield"]["alert"]["id"] == msgs[0]["alert_id"]


def test_unknown_alert_delivery_is_404(tmp_path):
    _, _, client = setup(tmp_path)
    assert client.get("/api/link/delivery/A-9999").status_code == 404
