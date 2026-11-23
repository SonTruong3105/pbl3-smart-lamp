"""EnergyVAD — Voice Activity Detection provider.

Energy-based VAD với adaptive threshold + hangover + trim silence:
- Không đốt frame đầu tiên khi user nói ngay
- Trim silence đầu/cuối trước khi gửi ASR
- Hangover tránh cắt giữa từ khi có tạp âm 1 frame
"""
import collections
from typing import Optional

import numpy as np
from loguru import logger


class EnergyVAD:
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 60,
        max_seconds: float = 30.0,
        silence_duration_ms: int = 700,
        min_speech_duration_ms: int = 300,
        energy_margin_db: float = 6.0,
        initial_threshold: float = 500.0,
        hangover_ms: int = 200,
        pre_speech_ms: int = 200,
        post_speech_ms: int = 300,
    ):
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.frame_samples = int(sample_rate * frame_duration_ms / 1000)
        self.max_samples = int(sample_rate * max_seconds)

        self.silence_duration_ms = silence_duration_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self.energy_margin_db = energy_margin_db
        self.hangover_frames = max(0, int(hangover_ms / frame_duration_ms))
        self.pre_speech_samples = int(pre_speech_ms / 1000 * sample_rate)
        self.post_speech_samples = int(post_speech_ms / 1000 * sample_rate)

        self.buffer = collections.deque(maxlen=self.max_samples)

        self.speech_frames = 0
        self.silence_frames = 0
        self.total_frames = 0
        self.is_in_speech = False
        self.noise_floor = initial_threshold
        self.threshold = initial_threshold

        self.calibrated = False
        self.calibration_frames = int(500 / frame_duration_ms)
        self._calibration_count = 0

        self.speech_start_sample: Optional[int] = None
        self.speech_end_sample: Optional[int] = None
        self._hangover_left = 0

    def push(self, pcm_bytes: bytes) -> bool:
        if not pcm_bytes:
            return False

        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(pcm) == 0:
            return False

        prev_len = len(self.buffer)
        self.buffer.extend(pcm)
        self.total_frames += 1

        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))

        # === Calibration: chỉ chạy khi frame im lặng ===
        if not self.calibrated:
            if rms < self.threshold:
                self.noise_floor = 0.7 * self.noise_floor + 0.3 * rms
                self.threshold = max(
                    200.0,
                    self.noise_floor * (10 ** (self.energy_margin_db / 20)),
                )
                self._calibration_count += 1
                if self._calibration_count >= self.calibration_frames:
                    self.calibrated = True
                return False
            self.calibrated = True
            logger.debug("🎤 Calibration kết thúc sớm (có tiếng nói)")

        # === VAD decision ===
        is_speech = rms > self.threshold

        if is_speech:
            self.speech_frames += 1
            self.silence_frames = 0
            self._hangover_left = self.hangover_frames

            if not self.is_in_speech:
                self.is_in_speech = True
                self.speech_start_sample = max(0, prev_len - self.pre_speech_samples)
                logger.debug(
                    f"🎤 Start-of-speech (rms={rms:.0f}, "
                    f"threshold={self.threshold:.0f})"
                )
            self.speech_end_sample = len(self.buffer)
        else:
            if self._hangover_left > 0:
                self._hangover_left -= 1
                self.speech_frames += 1
                self.speech_end_sample = len(self.buffer)
            else:
                self.silence_frames += 1
                self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms

        # === Check end-of-speech ===
        if self.is_in_speech:
            silence_ms = self.silence_frames * self.frame_duration_ms
            speech_ms = self.speech_frames * self.frame_duration_ms

            if (silence_ms >= self.silence_duration_ms
                    and speech_ms >= self.min_speech_duration_ms):
                logger.debug(
                    f"🎤 End-of-speech (speech={speech_ms}ms, "
                    f"silence={silence_ms}ms)"
                )
                return True

            if speech_ms >= 30000:
                logger.warning("⏰ Max speech duration (30s) — force end")
                return True

        return False

    def get_audio(self, trim: bool = True) -> bytes:
        if not self.buffer:
            return b""
        arr = np.array(self.buffer, dtype=np.int16)

        if trim and self.speech_start_sample is not None:
            start = self.speech_start_sample
            end = min(
                len(arr),
                (self.speech_end_sample or len(arr)) + self.post_speech_samples,
            )
            arr = arr[start:end]

        return arr.tobytes()

    def reset(self):
        self.buffer.clear()
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_in_speech = False
        self._hangover_left = 0
        self.speech_start_sample = None
        self.speech_end_sample = None

    def has_speech(self) -> bool:
        return self.speech_frames > 0

    def get_stats(self) -> dict:
        return {
            "total_frames": self.total_frames,
            "speech_frames": self.speech_frames,
            "silence_frames": self.silence_frames,
            "noise_floor": round(self.noise_floor, 1),
            "threshold": round(self.threshold, 1),
            "buffer_samples": len(self.buffer),
            "calibrated": self.calibrated,
        }


# Alias tương thích ngược
StreamingAudioBuffer = EnergyVAD