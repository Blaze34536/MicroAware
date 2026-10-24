"""Sun calibration sweep (M9): measure real packet loss at each Sun duty cycle.

Run with the three boards plugged in:  cd src && ../.venv/bin/python -m microaware.link.calibrate
Writes data/sun_calibration.json, which maps the dashboard's flare level (loss %) to Sun duty."""
import json
import struct
import time

import serial

from . import serial_frame
from .serial_link import CALIBRATION

COUNT, GAP_MS, SIZE = 500, 4, 247


def loss_from(payloads, sent):
    """Loss % from Earth payloads; counts distinct test frames (magic 0x7E + uint16 seq)."""
    seqs = {struct.unpack_from("<H", p, 1)[0] for p in payloads if len(p) >= 3 and p[0] == 0x7E}
    return round(100 * (1 - len(seqs) / sent), 1)


def run_step(habitat, earth, sun, duty):
    if sun is not None:
        sun.write(serial_frame.encode(struct.pack("<BBH", 0xF1, duty, 20)))
    time.sleep(0.5)
    earth.reset_input_buffer()
    habitat.write(serial_frame.encode(struct.pack("<BHHB", 0xC0, COUNT, GAP_MS, SIZE)))
    time.sleep(COUNT * GAP_MS / 1000 + 1.0)
    decoder, payloads = serial_frame.Decoder(), []
    while chunk := earth.read(4096):
        payloads += [p[5:] for p in decoder.feed(chunk)]  # strip rssi + millis
    return loss_from(payloads, COUNT)


def main():
    ports = serial_frame.find_ports()
    missing = {"habitat", "earth", "sun"} - ports.keys()
    if missing:
        raise SystemExit(f"Missing boards: {', '.join(sorted(missing))}. Found: {ports or 'none'}")
    opened = {role: serial.Serial(port, serial_frame.BAUD, timeout=0.2) for role, port in ports.items()}
    points = []
    for duty in range(0, 101, 10):
        loss = run_step(opened["habitat"], opened["earth"], opened["sun"], duty)
        points.append((duty, loss))
        print(f"Sun duty {duty:3d}%  ->  loss {loss:5.1f}%")
    opened["sun"].write(serial_frame.encode(struct.pack("<BBH", 0xF1, 0, 1)))  # Sun off
    CALIBRATION.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION.write_text(json.dumps({"points": points, "count": COUNT, "gap_ms": GAP_MS, "time": time.time()}))
    print(f"Saved {CALIBRATION}. Sun off: {points[0][1]}% loss (M8 needs under 1%).")
    if max(l for _, l in points) < 40:
        print("Loss never reached 40%: move the Sun next to Earth and shield Habitat (see firmware/README.md).")


if __name__ == "__main__":
    main()
