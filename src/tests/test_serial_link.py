import struct
import threading
import time

from microaware.link import serial_frame
from microaware.link.serial_link import SerialLink


class FakePort:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.written = bytearray()
        self.lock = threading.Lock()

    def read(self, n):
        with self.lock:
            out, self.incoming[:] = bytes(self.incoming[:n]), self.incoming[n:]
        if not out:
            time.sleep(0.01)
        return out

    def write(self, data):
        self.written += data


def earth_frame(data, rssi=-60, millis=1234):
    return serial_frame.encode(struct.pack("<bI", rssi, millis) + data)


def test_transmit_writes_one_framed_packet_per_frame():
    tx = FakePort()
    link = SerialLink(tx, FakePort())
    link.transmit([b"a" * 247, b"b" * 247], gap=0.001)
    assert serial_frame.Decoder().feed(bytes(tx.written)) == [b"a" * 247, b"b" * 247]


def test_earth_frames_reach_on_frame_with_rssi_stripped():
    rx = FakePort(b"ROLE earth\n" + earth_frame(b"hello") + earth_frame(b"world", rssi=-71))
    got = []
    link = SerialLink(FakePort(), rx)
    link.on_frame = got.append
    deadline = time.time() + 2
    while len(got) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert got == [b"hello", b"world"] and link.last_rssi == -71


def test_flare_commands_the_sun_using_calibration():
    sun = FakePort()
    link = SerialLink(FakePort(), FakePort(), sun, calibration=[(0, 0.5), (50, 20.0), (100, 60.0)])
    link.set_duty(40, seconds=30)  # 40% loss is between 20% (duty 50) and 60% (duty 100)
    (payload,) = serial_frame.Decoder().feed(bytes(sun.written))
    assert payload[0] == 0xF1 and payload[1] == 75 and struct.unpack("<H", payload[2:4])[0] == 30


def test_without_sun_board_flare_is_a_no_op():
    SerialLink(FakePort(), FakePort(), None).set_duty(50, seconds=10)
