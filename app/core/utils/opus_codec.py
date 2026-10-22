"""
Opus codec — wrapper cho ESP32.
- ESP32 → Backend: decode Opus → PCM (cho ASR)
- Backend → ESP32: encode PCM → Opus

LƯU Ý: Codec giữ state (prediction, gain) → KHÔNG dùng chung giữa các connection.
Mỗi ESP32ConnectionHandler tự tạo 1 instance riêng.
"""
import opuslib


class OpusCodec:
    def __init__(self, sample_rate: int = 16000, channels: int = 1, frame_ms: int = 60):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = int(sample_rate * frame_ms / 1000)  # samples per frame

        # Encoder: PCM → Opus
        self.encoder = opuslib.Encoder(
            sample_rate, channels, opuslib.APPLICATION_VOIP
        )
        self.encoder.bitrate = 16000
        self.encoder.complexity = 5

        # Decoder: Opus → PCM
        self.decoder = opuslib.Decoder(sample_rate, channels)

    def decode(self, opus_bytes: bytes) -> bytes:
        """Opus frame → PCM int16 LE."""
        try:
            return self.decoder.decode(opus_bytes, self.frame_size)
        except Exception as e:
            raise RuntimeError(f"Opus decode lỗi: {e}")


    def encode_frames(self, pcm_data: bytes) -> list:
        """PCM int16 LE → LIST các Opus frame riêng biệt."""
        frame_bytes = self.frame_size * 2
        frames = []
        for i in range(0, len(pcm_data), frame_bytes):
            chunk = pcm_data[i:i + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk += b"\x00" * (frame_bytes - len(chunk))
            try:
                frames.append(self.encoder.encode(chunk, self.frame_size))
            except Exception as e:
                raise RuntimeError(f"Opus encode lỗi: {e}")
        return frames

    def encode(self, pcm_data: bytes) -> bytes:
        """PCM int16 LE → Opus frames (nhiều frame nếu cần)."""
        frame_bytes = self.frame_size * 2  # int16 = 2 bytes
        out = []
        for i in range(0, len(pcm_data), frame_bytes):
            chunk = pcm_data[i:i + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk += b"\x00" * (frame_bytes - len(chunk))
            try:
                out.append(self.encoder.encode(chunk, self.frame_size))
            except Exception as e:
                raise RuntimeError(f"Opus encode lỗi: {e}")
        return b"".join(out)


# ✅ FIX: bỏ cache toàn cục — gây race khi nhiều ESP32 cùng lúc.
# Mỗi connection nên tự tạo OpusCodec() riêng.
# Nếu cần dùng chung (chỉ 1 client), có thể dùng hàm dưới đây nhưng KHÔNG khuyến nghị.
