"""
SileroVAD provider — dùng ONNX model để phát hiện giọng nói.
Chính xác hơn EnergyVAD, chống nhiễu tốt.

- Model: silero_vad.onnx (~2MB), chạy CPU
- Frame gốc: 512 samples (32ms @ 16kHz)
- Có buffer nội bộ: chấp nhận bất kỳ kích thước PCM
"""
import collections
from typing import Optional

import numpy as np
import onnxruntime as ort
from loguru import logger


class SileroVAD:
    """Wrapper SileroVAD với buffer nội bộ + double-threshold."""

    # Silero yêu cầu CHÍNH XÁC 512 samples cho mỗi lần inference
    FRAME_SIZE = 512

    def __init__(
        self,
        model_path: str = "models/snakers4_silero-vad/silero_vad.onnx",
        sample_rate: int = 16000,
        # Double-threshold
        threshold: float = 0.5,
        threshold_low: float = 0.2,
        # End-of-speech
        silence_duration_ms: int = 700,
        min_speech_duration_ms: int = 300,
        # Config khác (để tương thích interface EnergyVAD)
        frame_duration_ms: int = 60,
        max_seconds: float = 30.0,
        energy_margin_db: float = 6.0,
        initial_threshold: float = 500.0,
        hangover_ms: int = 200,
        pre_speech_ms: int = 200,
        post_speech_ms: int = 300,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.threshold_low = threshold_low
        self.silence_duration_ms = silence_duration_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self.frame_duration_ms = 32  # Silero frame cố định 32ms
        self.max_samples = int(sample_rate * max_seconds)

        # Buffer PCM thô (chưa qua model)
        self.pcm_buffer = collections.deque()
        self.pcm_buffer_len = 0

        # Buffer audio đã tích lũy khi đang speech
        self.audio_buffer = collections.deque(maxlen=self.max_samples)

        # ONNX session
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3  # Chỉ log lỗi
        self.session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )

        # State ONNX (stateful RNN)
        self._state = None
        self._context = None
        self._init_states()

        # VAD decision state
        self.is_in_speech = False
        self.speech_frames = 0     # Số frame speech liên tiếp
        self.silence_frames = 0    # Số frame silence liên tiếp
        self.total_frames = 0

        # Log threshold lần đầu
        logger.info(f"🎤 SileroVAD loaded | model={model_path}")

    def _init_states(self):
        """Reset state ONNX."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def _infer(self, frame: np.ndarray) -> float:
        """Chạy model cho 1 frame 512 samples. Trả về xác suất [0,1]."""
        x = frame.reshape(1, -1).astype(np.float32)
        x = np.concatenate((self._context, x), axis=1)

        ort_inputs = {
            "input": x,
            "state": self._state,
            "sr": np.array(self.sample_rate, dtype=np.int64),
        }
        out, self._state = self.session.run(None, ort_inputs)
        self._context = x[:, -64:]
        return float(out[0][0])

    def push(self, pcm_bytes: bytes) -> bool:
        """
        Nhận PCM bytes (int16 LE).
        Trả về True khi phát hiện kết thúc câu (end-of-speech).
        """
        if not pcm_bytes:
            return False

        # Buffer PCM thô
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        self.pcm_buffer.extend(pcm.tolist())
        self.pcm_buffer_len += len(pcm)

        # Xử lý từng frame 512 samples
        while self.pcm_buffer_len >= self.FRAME_SIZE:
            frame_list = [self.pcm_buffer.popleft() for _ in range(self.FRAME_SIZE)]
            self.pcm_buffer_len -= self.FRAME_SIZE
            frame = np.array(frame_list, dtype=np.float32) / 32768.0

            prob = self._infer(frame)
            self.total_frames += 1

            # === Double-threshold decision ===
            if not self.is_in_speech:
                if prob > self.threshold:
                    self.is_in_speech = True
                    self.speech_frames = 1
                    self.silence_frames = 0
                    logger.debug(f"🎤 Speech start (prob={prob:.2f})")
                else:
                    self.speech_frames = 0
            else:
                if prob < self.threshold_low:
                    self.silence_frames += 1
                    # Vẫn giữ frame vào buffer (để trim sau)
                else:
                    self.silence_frames = 0
                    self.speech_frames += 1

            # Lưu audio vào buffer khi đang speech
            if self.is_in_speech:
                self.audio_buffer.extend(frame_list)

            # === Check end-of-speech ===
            if self.is_in_speech:
                silence_ms = self.silence_frames * self.frame_duration_ms
                speech_ms = self.speech_frames * self.frame_duration_ms

                if (silence_ms >= self.silence_duration_ms
                        and speech_ms >= self.min_speech_duration_ms):
                    logger.info(
                        f"🎤 End-of-speech | speech={speech_ms}ms "
                        f"silence={silence_ms}ms prob={prob:.2f}"
                    )
                    return True

                # Force end nếu speech quá dài
                if speech_ms >= 8000:
                    logger.warning(f"⏰ Max speech (8s) — force end")
                    return True

        return False

    def get_audio(self, trim: bool = True) -> bytes:
        """Trả về PCM đã tích lũy (int16 LE)."""
        if not self.audio_buffer:
            return b""
        arr = np.array(self.audio_buffer, dtype=np.int16)
        return arr.tobytes()

    def reset(self):
        """Reset sau khi xử lý xong 1 câu."""
        self._init_states()
        self.pcm_buffer.clear()
        self.pcm_buffer_len = 0
        self.audio_buffer.clear()
        self.is_in_speech = False
        self.speech_frames = 0
        self.silence_frames = 0

    def has_speech(self) -> bool:
        return self.speech_frames > 0

    def get_stats(self) -> dict:
        return {
            "total_frames": self.total_frames,
            "speech_frames": self.speech_frames,
            "silence_frames": self.silence_frames,
            "is_in_speech": self.is_in_speech,
            "audio_samples": len(self.audio_buffer),
            "threshold": self.threshold,
            "threshold_low": self.threshold_low,
        }


# Alias để tương thích ngược
StreamingAudioBuffer = SileroVAD