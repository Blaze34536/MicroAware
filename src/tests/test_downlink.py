import numpy as np

from microaware import synth
from microaware.link.downlink import Downlink, SimLink, choose_mode, render_image

ALERT = {"id": "A-0001", "source": "fan_a", "kind": "machine_anomaly", "severity": "warning", "label": None,
         "evidence": {"score": 80.1, "threshold": 1.8, "top_bands": []}, "explanation": {"spoken": "x"}, "state": "active",
         "audio": "/api/voice/alert/A-0001.mp3"}


def test_mode_follows_weather_flare_and_priority_floor():
    assert choose_mode("calm", 0, "normal") == "calm"
    assert choose_mode("storm", 0, "normal") == "storm"
    assert choose_mode("calm", 60, "normal") == "storm"  # manual flare overrides calm weather
    assert choose_mode("calm", 20, "normal") == "storm"
    assert choose_mode("calm", 5, "normal") == "active"
    assert choose_mode("calm", 0, "critical") == "active"  # critical never below active


def test_evidence_image_is_96_by_72_grayscale():
    img = render_image(synth.whine(synth.fan(4, seed=1)))
    assert len(img) == 96 * 72 and max(img) > min(img)


def test_quiet_link_delivers_both_copies():
    dl = Downlink(SimLink(seed=1))
    rec = dl.send_alert(ALERT, bytes(96 * 72))
    assert rec["raw"]["delivered"] and rec["shield"]["delivered"] and rec["mode"] == "calm"
    assert dl.delivery("A-0001")["delivered"]


def test_flare_breaks_raw_but_storm_mode_delivers():
    dl = Downlink(SimLink(seed=2))
    dl.set_flare(40, seconds=60)
    wins = 0
    for i in range(10):
        rec = dl.send_alert(dict(ALERT, id=f"A-{i:04d}"), bytes(range(256)) * 27)
        assert rec["mode"] == "storm"
        wins += rec["shield"]["delivered"] and not rec["raw"]["delivered"]
    assert wins >= 9


def test_earth_decodes_the_alert_json_and_image():
    dl = Downlink(SimLink(seed=3))
    img = bytes(range(256)) * 27
    rec = dl.send_alert(ALERT, img)
    earth = dl.earth_view(rec["msg_id"])
    assert earth["shield"]["alert"]["id"] == "A-0001" and "audio" not in earth["shield"]["alert"]
    assert bytes(earth["shield"]["image"]) == img[: 96 * 72]


def test_sim_link_loss_tracks_flare_level():
    for level in (0, 20, 40):
        link = SimLink(seed=4)
        link.set_duty(level)
        lost = sum(not ok for ok in link.transmit_mask(n=2000, gap=0.015))
        assert abs(lost / 2000 - level / 100) < 0.06
