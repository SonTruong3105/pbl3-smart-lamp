"""
SileroVAD provider — dùng ONNX model để phát hiện giọng nói.
- Đã fix lỗi cắt mất chữ đầu (thêm pre_speech buffer)
"""
import collections
from typing import Optional
import numpy as np
import onnxruntime as ort
from loguru import logger


_SESSION_CACHE = {}


class SileroVAD:
    FRAME_SIZE = 512

    def __init__(
        self,
        model_path: str = "models/snakers4_silero-vad/silero_vad.onnx",
        sample_rate: int = 16000,
        threshold: float = 0.5,
        threshold_low: float = 0.2,
        silence_duration_ms: int = 700,
        min_speech_duration_ms: int = 300,
        frame_duration_ms: int = 60,
        max_seconds: float = 30.0,
        pre_speech_ms: int = 400,
        post_speech_ms: int = 300,
        **kwargs
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.threshold_low = threshold_low
        self.silence_duration_ms = silence_duration_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self.frame_duration_ms = 32
        self.max_samples = int(sample_rate * max_seconds)

        self.pre_speech_samples = int(pre_speech_ms / 1000 * sample_rate)
        self.post_speech_samples = int(post_speech_ms / 1000 * sample_rate)

        self.pcm_buffer = collections.deque()
        self.pcm_buffer_len = 0
        self.audio_buffer = collections.deque(maxlen=self.max_samples)
        self.pre_buffer = collections.deque(maxlen=self.pre_speech_samples)

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        cache_key = str(model_path)
        self.session = _SESSION_CACHE.get(cache_key)
        if self.session is None:
            self.session = ort.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
                sess_options=opts,
            )
            _SESSION_CACHE[cache_key] = self.session

        self._state = None
        self._context = None
        self._init_states()

        self.is_in_speech = False
        self.speech_frames = 0
        self.silence_frames = 0
        self.total_frames = 0
        logger.info(f"🎤 SileroVAD loaded | threshold={threshold} pre_ms={pre_speech_ms}")

    def _init_states(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def _infer(self, frame: np.ndarray) -> float:
        x = frame.reshape(1, -1).astype(np.float32)
        x = np.concatenate((self._context, x), axis=1)
        ort_inputs = {"input": x, "state": self._state, "sr": np.array(self.sample_rate, dtype=np.int64)}
        out, self._state = self.session.run(None, ort_inputs)
        self._context = x[:, -64:]
        return float(out[0][0])

    def push(self, pcm_bytes: bytes) -> bool:
        if not pcm_bytes: return False
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        self.pcm_buffer.extend(pcm.tolist())
        self.pcm_buffer_len += len(pcm)

        while self.pcm_buffer_len >= self.FRAME_SIZE:
            frame_list = [self.pcm_buffer.popleft() for _ in range(self.FRAME_SIZE)]
            self.pcm_buffer_len -= self.FRAME_SIZE
            frame = np.array(frame_list, dtype=np.float32) / 32768.0

            prob = self._infer(frame)
            self.total_frames += 1

            if not self.is_in_speech:
                self.pre_buffer.extend(frame_list)
                if prob > self.threshold:
                    self.is_in_speech = True
                    self.speech_frames = 1
                    self.silence_frames = 0
                    self.audio_buffer.extend(self.pre_buffer)
                    self.pre_buffer.clear()
                    logger.debug(f"🎤 Speech start (prob={prob:.2f})")
                else:
                    self.speech_frames = 0
            else:
                if prob < self.threshold_low:
                    self.silence_frames += 1
                else:
                    self.silence_frames = 0
                    self.speech_frames += 1

            if self.is_in_speech:
                self.audio_buffer.extend(frame_list)
                silence_ms = self.silence_frames * self.frame_duration_ms
                speech_ms = self.speech_frames * self.frame_duration_ms

                if (silence_ms >= self.silence_duration_ms and speech_ms >= self.min_speech_duration_ms):
                    logger.info(f"🎤 End-of-speech | speech={speech_ms}ms silence={silence_ms}ms")
                    return True
                # [PATCH P6] Đồng bộ với EnergyVAD — dùng config max_seconds
                max_speech_ms = int(self.max_samples / self.sample_rate * 1000)
                if speech_ms >= max_speech_ms:
                    logger.warning(f"⏰ Max speech {max_speech_ms}ms — force end")
                    return True
        return False

    def get_audio(self, trim: bool = True) -> bytes:
        if not self.audio_buffer: return b""
        return np.array(self.audio_buffer, dtype=np.int16).tobytes()

    def reset(self):
        self._init_states()
        self.pcm_buffer.clear()
        self.pcm_buffer_len = 0
        self.audio_buffer.clear()
        self.pre_buffer.clear()
        self.is_in_speech = False
        self.speech_frames = 0
        self.silence_frames = 0

    def has_speech(self) -> bool:
        return self.speech_frames > 0

    def get_stats(self) -> dict:
        return {"is_in_speech": self.is_in_speech, "audio_samples": len(self.audio_buffer)}

StreamingAudioBuffer = SileroVAD
