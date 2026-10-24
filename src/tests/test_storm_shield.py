import json

import numpy as np
import pytest

from microaware.link import packet
from microaware.link.packet import Receiver, build_message, encode, parse_message

ALERT = json.dumps({"id": "A-0007", "kind": "machine_anomaly", "evidence": {"score": 7.4}}).encode()
IMAGE = np.random.default_rng(0).integers(0, 256, 96 * 72, dtype=np.uint8).tobytes()


def receive(frames, keep=lambda i: True):
    rx = Receiver()
    for i, f in enumerate(frames):
        if keep(i):
            rx.feed(f)
    (result,) = rx.messages.values()
    return result


def test_message_round_trip():
    assert parse_message(build_message(ALERT, IMAGE)) == (ALERT, IMAGE)


def test_every_packet_fits_esp_now():
    assert all(len(f) <= 250 for f in encode(build_message(ALERT, IMAGE), 1, "storm", "critical"))


@pytest.mark.parametrize("mode", ["raw", "calm", "active", "storm"])
def test_lossless_link_delivers_in_every_mode(mode):
    msg = build_message(ALERT, IMAGE)
    r = receive(encode(msg, 3, mode, "normal"))
    assert r.delivered and r.message() == msg


def test_storm_survives_any_ten_frame_burst():
    frames = encode(build_message(ALERT, IMAGE), 1, "storm", "normal")
    for start in range(len(frames) - 10):
        r = receive(frames, keep=lambda i: not start <= i < start + 10)
        assert r.delivered, start


def test_interleaving_lets_calm_survive_a_burst_as_long_as_the_block_count():
    frames = encode(build_message(ALERT, IMAGE), 1, "calm", "normal")
    blocks = frames and Receiver.header(frames[0])["blocks"]
    for start in range(len(frames) - blocks):
        assert receive(frames, keep=lambda i: not start <= i < start + blocks).delivered


def test_raw_copy_with_a_lost_packet_is_not_delivered_but_keeps_the_rest():
    msg = build_message(ALERT, IMAGE)
    r = receive(encode(msg, 1, "raw", "normal"), keep=lambda i: i != 5)
    assert not r.delivered
    partial = r.message()
    assert len(partial) == len(msg)
    assert sum(a != b for a, b in zip(partial, msg)) <= packet.PAYLOAD  # only the lost share is blank


def test_critical_storm_sends_a_second_pass_of_new_parity():
    msg = build_message(ALERT, IMAGE)
    once = encode(msg, 1, "storm", "normal")
    twice = encode(msg, 1, "storm", "critical")
    assert len(twice) == 2 * len(once)
    # losing the whole first pass is survivable because pass two carries different shares
    assert receive(twice, keep=lambda i: i >= len(once)).delivered
    assert {Receiver.header(f)["idx"] for f in twice[len(once):]}.isdisjoint({Receiver.header(f)["idx"] for f in once})


def test_corrupted_packet_is_ignored():
    frames = encode(build_message(ALERT, IMAGE), 1, "calm", "normal")
    bad = bytearray(frames[0])
    bad[-1] ^= 0xFF
    rx = Receiver()
    rx.feed(bytes(bad))
    assert rx.messages == {} and rx.rejected == 1


def test_stats_count_rebuilt_packets():
    frames = encode(build_message(ALERT, IMAGE), 1, "active", "normal")
    r = receive(frames, keep=lambda i: i % 6 != 0)
    assert r.delivered and r.stats()["rebuilt"] > 0
