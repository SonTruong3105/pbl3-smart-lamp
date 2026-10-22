"""
AES-CTR cho UDP transport Xiaozhi — bản tương thích server gốc.

Gói UDP từ ESP32 có định dạng:
    [16 bytes nonce][encrypted payload]

Gói UDP server gửi xuống:
    [16 bytes nonce][encrypted payload]

Nonce dùng làm:
    1. Counter block cho AES-CTR
    2. Định danh định tuyến (tra ra device_id)
"""
import secrets
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class UdpCrypto:
    def __init__(self, key_hex: str, nonce_hex: str):
        self.key = bytes.fromhex(key_hex)
        self.nonce = bytes.fromhex(nonce_hex)
        assert len(self.key) in (16, 24, 32), f"Key phải 16/24/32 bytes, có {len(self.key)}"
        assert len(self.nonce) == 16, f"Nonce phải 16 bytes, có {len(self.nonce)}"

    def _cipher(self):
        return Cipher(algorithms.AES(self.key), modes.CTR(self.nonce))

    def decrypt_packet(self, packet: bytes) -> bytes:
        """Packet (đã bỏ nonce) -> plaintext payload."""
        if len(packet) == 0:
            return b""
        d = self._cipher().decryptor()
        return d.update(packet) + d.finalize()

    def encrypt_packet(self, payload: bytes) -> bytes:
        """Payload -> encrypted (KHÔNG gồm nonce)."""
        if len(payload) == 0:
            return b""
        e = self._cipher().encryptor()
        return e.update(payload) + e.finalize()



    def decrypt_with_packet_nonce(self, encrypted_payload: bytes, packet_nonce: bytes) -> bytes:
        """Giải mã dùng nonce ĐẦY ĐỦ từ gói tin (16 byte)."""
        if len(packet_nonce) != 16:
            raise ValueError("Packet nonce must be 16 bytes")
        cipher = Cipher(algorithms.AES(self.key), modes.CTR(packet_nonce))
        decryptor = cipher.decryptor()
        return decryptor.update(encrypted_payload) + decryptor.finalize()

    def encrypt_with_packet_nonce(self, payload: bytes, packet_nonce: bytes) -> bytes:
        """Mã hóa dùng nonce ĐẦY ĐỦ từ gói tin."""
        if len(packet_nonce) != 16:
            raise ValueError("Packet nonce must be 16 bytes")
        cipher = Cipher(algorithms.AES(self.key), modes.CTR(packet_nonce))
        encryptor = cipher.encryptor()
        return encryptor.update(payload) + encryptor.finalize()

def generate_key_nonce():
    """Sinh cặp key/nonce mới cho 1 phiên."""
    key_hex = secrets.token_hex(16)
    nonce_hex = secrets.token_hex(16)
    return key_hex, nonce_hex