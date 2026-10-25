from microaware.link.serial_frame import Decoder, crc8, encode


def test_crc8_known_value():
    # CRC-8/SMBUS (poly 0x07, init 0) check value
    assert crc8(b"123456789") == 0xF4


def test_round_trip():
    payload = bytes(range(250))
    frame = encode(payload)
    assert frame[0] == 0xA5 and frame[1] == 250 and len(frame) == 253
    assert Decoder().feed(frame) == [payload]


def test_multiple_frames_in_one_feed():
    assert Decoder().feed(encode(b"a") + encode(b"bc")) == [b"a", b"bc"]


def test_resync_after_garbage_and_text():
    data = b"\x00\xffjunk" + b"ROLE earth\n" + encode(b"one") + b"# debug line\n" + encode(b"two")
    assert Decoder().feed(data) == [b"one", b"two"]


def test_text_containing_sync_byte():
    # A stray 0xA5 in garbage must not swallow the following real frame.
    assert Decoder().feed(b"\xa5\x03xyz" + encode(b"ok")) == [b"ok"]


def test_bad_crc_dropped():
    bad = bytearray(encode(b"hello"))
    bad[-1] ^= 0xFF
    assert Decoder().feed(bytes(bad) + encode(b"next")) == [b"next"]


def test_frame_split_across_feeds():
    frame = encode(b"split me")
    d = Decoder()
    out = []
    for i in range(len(frame)):
        out += d.feed(frame[i:i + 1])
    assert out == [b"split me"]


def test_encode_rejects_bad_length():
    import pytest
    with pytest.raises(ValueError):
        encode(b"")
    with pytest.raises(ValueError):
        encode(bytes(251))
