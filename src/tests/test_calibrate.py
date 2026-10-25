import struct

from microaware.link.calibrate import loss_from

def test_loss_counts_distinct_test_frames_only():
    test = lambda seq: bytes([0x7E]) + struct.pack("<H", seq) + bytes(244)
    payloads = [test(0), test(1), test(1), test(3), b"\x5a" + bytes(246)]  # dup and a non-test frame
    assert loss_from(payloads, sent=4) == 25.0
