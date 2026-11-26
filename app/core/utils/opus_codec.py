"""
Opus codec — wrapper tối ưu cho ESP32 (hỗ trợ cả Thoại độ trễ thấp & Nhạc toàn dải).
- ESP32 → Backend: decode Opus → PCM (16 kHz cho ASR)
- Backend → ESP32: encode PCM → Opus (Voice VOIP mode hoặc Music AUDIO mode)

LƯU Ý: Codec giữ state (prediction, gain) → KHÔNG dùng chung giữa các connection.
Mỗi ESP32ConnectionHandler tự tạo 1 instance riêng.
"""
from __future__ import annotations

import opuslib

# Hằng số CTL của libopus (fallback an toàn nếu wrapper không expose sẵn)
_OPUS_SET_SIGNAL_REQUEST = 4024
_OPUS_SIGNAL_VOICE = 3001
_OPUS_SIGNAL_MUSIC = 3002
_OPUS_SET_VBR_REQUEST = 4006


class OpusCodec:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_ms: int = 60,
        output_sample_rate: int | None = None,
        voice_bitrate: int = 24000,
        music_bitrate: int = 64000,
    ):
        self.sample_rate = sample_rate
        self.output_sample_rate = output_sample_rate or sample_rate
        self.channels = channels
        self.frame_ms = frame_ms

        # Kích thước frame (samples) cho chiều thu (ASR) và chiều phát (TTS/Music)
        self.in_frame_size = int(self.sample_rate * frame_ms / 1000)
        self.out_frame_size = int(self.output_sample_rate * frame_ms / 1000)
        self.frame_size = self.in_frame_size  # Giữ thuộc tính cũ để tương thích ngược

        self.voice_bitrate = voice_bitrate
        self.music_bitrate = music_bitrate
        self._mode = "voice"

        # 1. Encoder tối ưu cho giọng nói TTS (độ trễ thấp, rõ tiếng)
        self.voice_encoder = self._build_encoder(
            sample_rate=self.output_sample_rate,
            channels=channels,
            application=opuslib.APPLICATION_VOIP,
            bitrate=voice_bitrate,
            complexity=5,
            signal=_OPUS_SIGNAL_VOICE,
        )

        # 2. Encoder tối ưu cho phát nhạc (full-band/super-wideband, giàu hài âm)
        self.music_encoder = self._build_encoder(
            sample_rate=self.output_sample_rate,
            channels=channels,
            application=opuslib.APPLICATION_AUDIO,
            bitrate=music_bitrate,
            complexity=10,
            signal=_OPUS_SIGNAL_MUSIC,
        )

        # Trỏ mặc định self.encoder về voice_encoder để tương thích code cũ
        self.encoder = self.voice_encoder

        # 3. Decoder: Opus từ Mic ESP32 → PCM cho ASR
        self.decoder = opuslib.Decoder(self.sample_rate, channels)

    @staticmethod
    def _build_encoder(
        sample_rate: int,
        channels: int,
        application: int,
        bitrate: int,
        complexity: int,
        signal: int,
    ) -> opuslib.Encoder:
        enc = opuslib.Encoder(sample_rate, channels, application)
        enc.bitrate = bitrate
        enc.complexity = complexity
        try:
            enc.set_ctl(_OPUS_SET_VBR_REQUEST, 1)
            enc.set_ctl(_OPUS_SET_SIGNAL_REQUEST, signal)
        except Exception:
            pass
        return enc

    def set_music_mode(self, bitrate: int | None = None) -> None:
        """Chuyển sang encoder nhạc chất lượng cao và reset state sạch."""
        if bitrate is not None and bitrate != self.music_bitrate:
            self.music_bitrate = bitrate
            self.music_encoder.bitrate = bitrate
        try:
            self.music_encoder.reset_state()
        except Exception:
            pass
        self._mode = "music"
        self.encoder = self.music_encoder

    def set_voice_mode(self, bitrate: int | None = None) -> None:
        """Quay về encoder giọng nói TTS."""
        if bitrate is not None and bitrate != self.voice_bitrate:
            self.voice_bitrate = bitrate
            self.voice_encoder.bitrate = bitrate
        self._mode = "voice"
        self.encoder = self.voice_encoder

    def decode(self, opus_bytes: bytes) -> bytes:
        """Opus frame → PCM int16 LE."""
        try:
            return self.decoder.decode(opus_bytes, self.in_frame_size)
        except Exception as e:
            raise RuntimeError(f"Opus decode lỗi: {e}")

    def _encode_with(self, encoder: opuslib.Encoder, pcm_data: bytes) -> list[bytes]:
        if not pcm_data:
            return []
        frame_bytes = self.out_frame_size * self.channels * 2  # int16 = 2 bytes/sample
        view = memoryview(pcm_data)
        total_len = len(view)
        frames: list[bytes] = []

        for offset in range(0, total_len, frame_bytes):
            chunk = view[offset : offset + frame_bytes]
            if len(chunk) < frame_bytes:
                padded = bytearray(frame_bytes)
                padded[: len(chunk)] = chunk
                buf = bytes(padded)
            else:
                buf = bytes(chunk)
            try:
                frames.append(encoder.encode(buf, self.out_frame_size))
            except Exception as e:
                raise RuntimeError(f"Opus encode lỗi: {e}")
        return frames

    def encode_frames(self, pcm_data: bytes, music: bool = False) -> list[bytes]:
        """PCM int16 LE → LIST các Opus frame riêng biệt.
        Truyền `music=True` (hoặc gọi `set_music_mode()`) để mã hóa nhạc ở 48kbps AUDIO mode.
        """
        enc = self.music_encoder if (music or self._mode == "music") else self.voice_encoder
        return self._encode_with(enc, pcm_data)

    def encode_music_frames(self, pcm_data: bytes) -> list[bytes]:
        """Helper chuyên dụng: encode toàn bộ PCM nhạc sang Opus AUDIO 48kbps."""
        try:
            self.music_encoder.reset_state()
        except Exception:
            pass
        return self._encode_with(self.music_encoder, pcm_data)

    def encode(self, pcm_data: bytes, music: bool = False) -> bytes:
        """PCM int16 LE → Opus bytes nối liền."""
        return b"".join(self.encode_frames(pcm_data, music=music))