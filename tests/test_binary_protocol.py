"""Contract test — binary framing v1/v2/v3 theo firmware websocket_protocol.cc."""
import struct

from app.core.protocols.binary import unwrap_opus_frame, wrap_opus_frame

OPUS = b"\xf8\xff\xfeOPUSPAYLOAD"


def test_v1_raw_opus_unchanged():
    assert unwrap_opus_frame(OPUS, 1) == OPUS
    assert wrap_opus_frame(OPUS, 1) == OPUS


def test_v2_strips_16_byte_header():
    # >HHIII = version, type, reserved, timestamp, payload_size (network byte order)
    frame = struct.pack(">HHIII", 2, 0, 0, 12345, len(OPUS)) + OPUS
    assert unwrap_opus_frame(frame, 2) == OPUS


def test_v3_strips_4_byte_header():
    # >BBH = type, reserved, payload_size
    frame = struct.pack(">BBH", 0, 0, len(OPUS)) + OPUS
    assert unwrap_opus_frame(frame, 3) == OPUS


def test_wrap_roundtrip_v2_v3():
    for version in (2, 3):
        wrapped = wrap_opus_frame(OPUS, version)
        assert unwrap_opus_frame(wrapped, version) == OPUS


def test_v2_wrapped_header_fields():
    wrapped = wrap_opus_frame(OPUS, 2)
    version, type_, reserved, timestamp, size = struct.unpack(">HHIII", wrapped[:16])
    assert (version, type_, reserved, timestamp, size) == (2, 0, 0, 0, len(OPUS))
    assert wrapped[16:] == OPUS


def test_truncated_header_returns_none():
    assert unwrap_opus_frame(b"\x00", 2) is None
    assert unwrap_opus_frame(b"\x00\x00", 3) is None


def test_zero_payload_returns_none():
    assert unwrap_opus_frame(struct.pack(">HHIII", 2, 0, 0, 0, 0), 2) is None


def test_unknown_version_treated_as_raw():
    assert unwrap_opus_frame(OPUS, 99) == OPUS
