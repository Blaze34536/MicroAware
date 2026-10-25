"""The real radio: laptop -> Habitat ESP32 -> ESP-NOW -> Earth ESP32 -> laptop, with the Sun ESP32 as interferer."""
import json
import struct
import threading
import time
from pathlib import Path

import numpy as np

from . import serial_frame

CALIBRATION = Path("data/sun_calibration.json")


class SerialLink:
    name = "radio"

    def __init__(self, habitat, earth, sun=None, calibration=None):
        """habitat/earth/sun: open serial ports (anything with read/write). calibration: [(duty %, loss %)]."""
        self.habitat, self.earth, self.sun = habitat, earth, sun
        self.calibration = calibration
        self._on_frame = None
        self.last_rssi = None
        self.duty = 0

    @property
    def on_frame(self):
        return self._on_frame

    @on_frame.setter
    def on_frame(self, callback):
        # start reading only once someone listens, so no early frame is dropped
        started, self._on_frame = self._on_frame is not None, callback
        if not started:
            threading.Thread(target=self._read_earth, daemon=True).start()

    def _read_earth(self):
        decoder = serial_frame.Decoder()
        while True:
            for payload in decoder.feed(self.earth.read(512)):
                if len(payload) > 5:
                    self.last_rssi = struct.unpack_from("<b", payload)[0]
                    self.on_frame(payload[5:])  # strip rssi (1 B) + millis (4 B)

    def transmit(self, frames, gap):
        for frame in frames:
            self.habitat.write(serial_frame.encode(frame))
            time.sleep(gap)

    def duty_for_loss(self, loss_pct):
        """Flare level means measured loss; the calibration sweep maps it to the Sun's duty cycle."""
        if not self.calibration or loss_pct <= 0:
            return int(loss_pct)
        duty, loss = zip(*sorted(self.calibration, key=lambda p: p[1]))
        return int(round(np.interp(loss_pct, loss, duty)))

    def set_duty(self, loss_pct, seconds=30):
        self.duty = self.duty_for_loss(loss_pct)
        if self.sun is not None:
            self.sun.write(serial_frame.encode(struct.pack("<BBH", 0xF1, self.duty, int(seconds))))


def open_radio():
    """Find the boards by their ROLE line; returns a SerialLink, or None without Habitat + Earth."""
    import serial

    ports = serial_frame.find_ports()
    if not {"habitat", "earth"} <= ports.keys():
        return None
    open_port = lambda role: serial.Serial(ports[role], serial_frame.BAUD, timeout=0.05)
    calibration = json.loads(CALIBRATION.read_text())["points"] if CALIBRATION.exists() else None
    print(f"Radio link on {ports}")
    return SerialLink(open_port("habitat"), open_port("earth"), open_port("sun") if "sun" in ports else None, calibration)
