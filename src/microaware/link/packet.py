"""Storm Shield: alert message -> erasure-coded, interleaved ESP-NOW packets, and back."""
import binascii
import struct
import zlib
from dataclasses import dataclass, field

import zfec

MAGIC, VERSION = 0x5A, 1
HEAD = struct.Struct("<BBHBBBBBBBH")  # magic ver msg_id block blocks idx k n mode priority msg_len
CRC = struct.Struct("<H")
PAYLOAD = 230  # 13 B header + 2 B crc16 + 230 = 245 B: what Earth can forward after its 5 B rssi + millis header
MAX_SHARES = 32  # storm critical sends 2 x 12 shares

# mode -> (code, k, n, frame gap seconds)
MODES = {"raw": (0, 4, 4, 0.004), "calm": (1, 4, 5, 0.004), "active": (2, 4, 6, 0.008), "storm": (3, 4, 12, 0.015)}  # 4 of 12: measured ~100% delivery up to 40% random burst loss (8 shares failed at 30%)
PRIORITIES = {"critical": 0, "normal": 1, "routine": 2}


def build_message(alert_json: bytes, image: bytes) -> bytes:
    body = struct.pack("<H", len(alert_json)) + alert_json + image
    return body + struct.pack("<I", zlib.crc32(body))


def parse_message(msg: bytes):
    body, (crc,) = msg[:-4], struct.unpack("<I", msg[-4:])
    if zlib.crc32(body) != crc:
        raise ValueError("message CRC-32 mismatch")
    (n,) = struct.unpack("<H", body[:2])
    return body[2 : 2 + n], body[2 + n :]


def encode(msg: bytes, msg_id: int, mode: str, priority: str):
    """Packets in airing order: share 0 of every block, then share 1 of every block, ..."""
    code, k, n, _ = MODES[mode]
    padded = msg + bytes(-len(msg) % (k * PAYLOAD))
    blocks = len(padded) // (k * PAYLOAD)
    passes = [range(n)]
    if mode == "storm" and priority == "critical":
        passes.append(range(n, 2 * n))  # fresh parity, so every frame that gets through adds information
    shares = []
    for b in range(blocks):
        data = [padded[(b * k + i) * PAYLOAD : (b * k + i + 1) * PAYLOAD] for i in range(k)]
        ids = [i for p in passes for i in p]
        shares.append(dict(zip(ids, zfec.Encoder(k, MAX_SHARES).encode(data, ids))))
    frames = []
    for idx in (i for p in passes for i in p):
        for b in range(blocks):
            head = HEAD.pack(MAGIC, VERSION, msg_id & 0xFFFF, b, blocks, idx, k, n, code, PRIORITIES[priority], len(msg))
            body = head + shares[b][idx]
            frames.append(body + CRC.pack(binascii.crc_hqx(body, 0xFFFF)))
    return frames


@dataclass
class Reception:
    head: dict
    shares: dict = field(default_factory=dict)  # block -> {idx: payload}
    frames: int = 0

    def _block(self, b):
        k = self.head["k"]
        got = self.shares.get(b, {})
        if len(got) >= k:
            ids = sorted(got)[:k]
            return zfec.Decoder(k, MAX_SHARES).decode([got[i] for i in ids], ids), True
        return [got.get(i, bytes(PAYLOAD)) for i in range(k)], False  # missing data shares stay black

    @property
    def delivered(self):
        if not all(self._block(b)[1] for b in range(self.head["blocks"])):
            return False
        try:
            parse_message(self.message())
            return True
        except ValueError:
            return False

    def message(self):
        """The message bytes, with unrecoverable shares zero-filled."""
        out = b"".join(b"".join(self._block(b)[0]) for b in range(self.head["blocks"]))
        return out[: self.head["msg_len"]]

    def stats(self):
        k, blocks = self.head["k"], self.head["blocks"]
        rebuilt = sum(k - sum(i < k for i in self.shares.get(b, {})) for b in range(blocks) if self._block(b)[1])
        return {
            "frames": self.frames,
            "rebuilt": rebuilt,
            "unrecoverable_blocks": sum(not self._block(b)[1] for b in range(blocks)),
            "blocks": blocks,
        }


class Receiver:
    def __init__(self):
        self.messages = {}  # (msg_id, mode) -> Reception; raw and shielded copies share an id
        self.rejected = 0

    @staticmethod
    def header(frame):
        keys = ("magic", "version", "msg_id", "block", "blocks", "idx", "k", "n", "mode", "priority", "msg_len")
        return dict(zip(keys, HEAD.unpack_from(frame)))

    def feed(self, frame: bytes):
        body = frame[:-2]
        if len(frame) != HEAD.size + PAYLOAD + CRC.size or CRC.unpack(frame[-2:])[0] != binascii.crc_hqx(body, 0xFFFF):
            self.rejected += 1
            return None
        h = self.header(frame)
        if h["magic"] != MAGIC or h["version"] != VERSION:
            self.rejected += 1
            return None
        key = (h["msg_id"], h["mode"])
        rec = self.messages.setdefault(key, Reception(h))
        rec.frames += 1
        rec.shares.setdefault(h["block"], {}).setdefault(h["idx"], body[HEAD.size :])
        return key
