"""Kiểm tra VieNeu-TTS đang chạy trên GPU hay CPU."""
from vieneu import Vieneu
import torch

print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")

tts = Vieneu()

# In ra device mà model đang dùng (tùy SDK có expose hay không)
if hasattr(tts, "device"):
    print(f"VieNeu device: {tts.device}")
elif hasattr(tts, "_device"):
    print(f"VieNeu device: {tts._device}")
else:
    print("Không tìm thấy thuộc tính 'device' — kiểm tra attribute khác:")
    for attr in dir(tts):
        if "device" in attr.lower() or "gpu" in attr.lower():
            print(f"  - {attr}: {getattr(tts, attr, '?')}")

tts.close()