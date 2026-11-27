import os
import threading
import numpy as np
import torch
from scipy.signal import butter, iirnotch, resample_poly, sosfilt, sosfilt_zi, tf2sos
from df.enhance import enhance, init_df
from df.utils import get_cache_dir
from libdf import DF

_DF_MODEL = None
_DF_LOCK = threading.Lock()
_DF_INFERENCE_LOCK = threading.Lock()


def _build_hum_filter_sos(sample_rate: int = 16000) -> np.ndarray:
    """
    Tạo chuỗi bộ lọc SOS (Second-Order Sections) ổn định số học ở 16 kHz:
    1. High-pass Butterworth bậc 4 tại 100 Hz: cắt tiếng ù trầm dưới dải giọng nói.
    2. Notch 50 Hz & 100 Hz (Q=25): triệt nhiễu điện lưới và sóng hài nguồn xung.
    """
    hp_sos = butter(4, 100.0, btype="highpass", fs=sample_rate, output="sos")
    b50, a50 = iirnotch(50.0, Q=25.0, fs=sample_rate)
    b100, a100 = iirnotch(100.0, Q=25.0, fs=sample_rate)
    return np.vstack([hp_sos, tf2sos(b50, a50), tf2sos(b100, a100)]).astype(np.float32)


_HUM_FILTER_SOS = _build_hum_filter_sos(16000)


def get_shared_df3_model():
    global _DF_MODEL
    if _DF_MODEL is None:
        with _DF_LOCK:
            if _DF_MODEL is None:
                os.environ["DEVICE"] = "cpu"
                try:
                    model, _, _ = init_df(
                        model_base_dir=os.path.join(get_cache_dir(), "DeepFilterNet3"),
                        post_filter=False,
                        config_allow_defaults=True,
                        log_file=None,
                    )
                    model = model.to("cpu").eval()
                finally:
                    os.environ.pop("DEVICE", None)
                _DF_MODEL = model
    return _DF_MODEL


class DeepFilterNet3StreamDenoiser:
    """
    Khử nhiễu streaming hoặc nguyên câu (utterance) cho PCM16 16 kHz:
    - Lọc thông cao 100 Hz + notch 50/100 Hz để triệt tiếng ù nguồn trước khi khử nhiễu.
    - Chừa headroom 0.85x tránh méo đỉnh khi resample 16k -> 48k.
    - Hỗ trợ flush_end=True cho file WAV nguyên câu để làm ấm state đầu câu
      và không bỏ rơi phần mẫu dư cuối câu.
    """
    def __init__(self, atten_lim_db: float = 30.0):
        self.model = get_shared_df3_model()
        self.df_state = DF(sr=48000, fft_size=960, hop_size=480, nb_bands=32)
        self.atten_lim_db = atten_lim_db
        self._residual_48k = np.empty(0, dtype=np.float32)
        self._filter_zi = None

    def reset(self):
        self.df_state = DF(sr=48000, fft_size=960, hop_size=480, nb_bands=32)
        self._residual_48k = np.empty(0, dtype=np.float32)
        self._filter_zi = None

    def _remove_hum_16k(self, audio_16k: np.ndarray, stateless: bool) -> np.ndarray:
        if audio_16k.size == 0:
            return audio_16k
        if stateless:
            zi = sosfilt_zi(_HUM_FILTER_SOS) * audio_16k[0]
            filtered, _ = sosfilt(_HUM_FILTER_SOS, audio_16k, zi=zi)
            return filtered.astype(np.float32)

        if self._filter_zi is None:
            self._filter_zi = sosfilt_zi(_HUM_FILTER_SOS) * audio_16k[0]
        filtered, self._filter_zi = sosfilt(_HUM_FILTER_SOS, audio_16k, zi=self._filter_zi)
        return filtered.astype(np.float32)

    def process_pcm16_16k(self, pcm_bytes: bytes, flush_end: bool = False) -> bytes:
        if not pcm_bytes:
            return pcm_bytes

        # Giảm nhẹ 15% biên độ trước resample để tránh intersample clipping ở mic INMP441
        audio_16k = (np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0) * 0.85
        audio_16k = self._remove_hum_16k(audio_16k, stateless=flush_end)
        orig_len_16k = len(audio_16k)

        warmup_16k = 0
        if flush_end and orig_len_16k > 0:
            # Lặp lại 160ms đầu tiên làm đoạn mồi để DF ổn định state trước chữ đầu tiên
            warmup_16k = min(2560, orig_len_16k)
            audio_16k = np.concatenate([audio_16k[:warmup_16k], audio_16k])

        audio_48k = resample_poly(audio_16k, up=3, down=1).astype(np.float32)

        if self._residual_48k.size > 0:
            audio_48k = np.concatenate([self._residual_48k, audio_48k])

        hop = 480
        if flush_end:
            rem = len(audio_48k) % hop
            if rem != 0:
                audio_48k = np.pad(audio_48k, (0, hop - rem), mode="constant")
            usable_len = len(audio_48k)
            self._residual_48k = np.empty(0, dtype=np.float32)
        else:
            usable_len = (len(audio_48k) // hop) * hop
            self._residual_48k = audio_48k[usable_len:]
            if usable_len == 0:
                return b""

        chunk_48k = audio_48k[:usable_len]
        tensor_48k = torch.from_numpy(chunk_48k).unsqueeze(0)

        with _DF_INFERENCE_LOCK, torch.no_grad():
            enhanced_48k = enhance(
                self.model,
                self.df_state,
                tensor_48k,
                atten_lim_db=self.atten_lim_db,
            ).squeeze(0).numpy()

        enhanced_16k = resample_poly(enhanced_48k, up=1, down=3)
        if flush_end:
            enhanced_16k = enhanced_16k[warmup_16k : warmup_16k + orig_len_16k]

        out_int16 = np.clip(enhanced_16k * 32768.0, -32768, 32767).astype(np.int16)
        return out_int16.tobytes()