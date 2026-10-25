"""Serial framing for the ESP32 link: 0xA5, len, payload, crc8(len + payload)."""
import time

SYNC = 0xA5
MAX_PAYLOAD = 250
BAUD = 921600


def crc8(data) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def encode(payload: bytes) -> bytes:
    if not 1 <= len(payload) <= MAX_PAYLOAD:
        raise ValueError(f"payload length {len(payload)} not in 1..{MAX_PAYLOAD}")
    body = bytes([len(payload)]) + bytes(payload)
    return bytes([SYNC]) + body + bytes([crc8(body)])


class Decoder:
    """Stream decoder. Skips anything that isn't a valid frame (text lines, noise)."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buf += data
        out = []
        while True:
            start = self.buf.find(SYNC)
            if start < 0:
                self.buf.clear()
                return out
            del self.buf[:start]
            if len(self.buf) < 2:
                return out
            n = self.buf[1]
            if not 1 <= n <= MAX_PAYLOAD:
                del self.buf[0]
                continue
            if len(self.buf) < n + 3:
                return out
            body = bytes(self.buf[1:n + 2])
            if crc8(body) == self.buf[n + 2]:
                out.append(body[1:])
                del self.buf[:n + 3]
            else:
                del self.buf[0]  # false sync: rescan from the next byte


def _read_role(ser, deadline):
    line = b""
    while time.monotonic() < deadline:
        line += ser.read(64)
        while b"\n" in line:
            text, line = line.split(b"\n", 1)
            text = text.strip()
            if text.startswith(b"ROLE "):
                return text[5:].decode(errors="replace").strip()
    return None


def find_ports(timeout: float = 3.0) -> dict:
    """Open each USB serial port and map the board's ROLE line to its port."""
    import serial
    from serial.tools import list_ports

    roles = {}
    for port in sorted(p.device for p in list_ports.comports() if p.vid is not None):  # USB only: /dev/ttyUSB0, COM3, ...
        try:
            with serial.Serial(port, BAUD, timeout=0.05) as ser:
                start = time.monotonic()
                # The ROLE line only prints at boot, so pulse EN low (RTS) with IO0 high (DTR off).
                ser.dtr = False
                ser.rts = True
                time.sleep(0.1)
                ser.rts = False
                ser.reset_input_buffer()
                role = _read_role(ser, start + timeout)
        except (OSError, serial.SerialException):
            continue
        if role:
            roles[role] = port
    return roles
