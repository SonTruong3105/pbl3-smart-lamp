import serial
import wave

PORT = "COM7"       # Đổi thành cổng COM của ESP32
BAUD = 921600
RATE = 16000
SECONDS = 5
OUT_FILE = "test_mic.wav"

ser = serial.Serial(PORT, BAUD, timeout=1)
ser.reset_input_buffer()

total_bytes = RATE * 2 * SECONDS  # 16000 mẫu/s * 2 bytes/mẫu * 5 giây = 160,000 bytes
audio_data = bytearray()

print(f"🎙️ Đang ghi âm {SECONDS} giây từ ESP32... Hãy nói vào mic!")

try:
    while len(audio_data) < total_bytes:
        chunk = ser.read(min(1024, total_bytes - len(audio_data)))
        if chunk:
            audio_data.extend(chunk)
            print(f"Đã nhận: {len(audio_data)} / {total_bytes} bytes", end="\r")
except Exception as e:
    print(f"\n❌ Lỗi đọc Serial: {e}")
finally:
    ser.close()

with wave.open(OUT_FILE, "wb") as wf:
    wf.setnchannels(1)       # Mono
    wf.setsampwidth(2)       # 16-bit
    wf.setframerate(RATE)    # 16000 Hz
    wf.writeframes(audio_data)

print(f"✅ Đã lưu xong file: {OUT_FILE} ({len(audio_data)} bytes)")