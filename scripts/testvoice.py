from vieneu import Vieneu

tts = Vieneu()

# Test 4 giọng phổ biến
VOICES = [
    "Minh Quân Pro",   # Nam Bắc, tự nhiên
    "Trúc Ly",         # Nữ Bắc, tự nhiên
    "Ngọc Huyền",      # Nữ Bắc
    "Thùy Dung",       # Nữ Nam, tin tức
]

TEXT = "Xin chào, tôi là trợ lý ảo Xiaozhi. Hôm nay trời đẹp, bạn có muốn tôi tra thời tiết không?"

for voice in VOICES:
    print(f"🎙️ Đang tạo: {voice}...")
    audio = tts.infer(TEXT, voice=voice)
    filename = f"test_{voice.replace(' ', '_')}.wav"
    tts.save(audio, filename)
    print(f"   💾 {filename}")

tts.close()
print("\n✅ Xong! Nghe thử từng file để chọn giọng ưng ý.")