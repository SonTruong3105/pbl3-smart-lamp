"""Unit tests cho UdpCrypto (AES-CTR roundtrip)."""
import pytest

from app.core.utils.udp_crypto import UdpCrypto, generate_key_nonce


class TestUdpCrypto:
    def test_roundtrip_packet(self):
        key, nonce = generate_key_nonce()
        c = UdpCrypto(key, nonce)
        plain = b"hello world"
        enc = c.encrypt_packet(plain)
        assert c.decrypt_packet(enc) == plain

    def test_empty_roundtrip(self):
        key, nonce = generate_key_nonce()
        c = UdpCrypto(key, nonce)
        assert c.encrypt_packet(b"") == b""
        assert c.decrypt_packet(b"") == b""

    def test_different_nonce_different_cipher(self):
        key, _ = generate_key_nonce()
        c1 = UdpCrypto(key, "00" * 16)
        c2 = UdpCrypto(key, "ff" * 16)
        plain = b"same input"
        assert c1.encrypt_packet(plain) != c2.encrypt_packet(plain)

    def test_with_packet_nonce_roundtrip(self):
        key, _ = generate_key_nonce()
        c = UdpCrypto(key, "00" * 16)
        pnonce = bytes.fromhex("01" + "00" * 15)
        enc = c.encrypt_with_packet_nonce(b"hi there", pnonce)
        dec = c.decrypt_with_packet_nonce(enc, pnonce)
        assert dec == b"hi there"

    def test_wrong_nonce_length_raises(self):
        key, _ = generate_key_nonce()
        c = UdpCrypto(key, "00" * 16)
        with pytest.raises(ValueError):
            c.encrypt_with_packet_nonce(b"x", b"short")

    def test_invalid_key_length_raises(self):
        with pytest.raises(AssertionError):
            UdpCrypto("00" * 8, "00" * 16)   # key 8 bytes