from vieneu import Vieneu

print("🔧 Đang khởi tạo VieNeu-TTS...")
tts = Vieneu()
print("✅ Khởi tạo thành công!\n")

# Test với giọng mặc định
text = "Xin chào, tôi là trợ lý ảo Xiaozhi. Tôi có thể nói tiếng Việt rất tự nhiên."
audio = tts.infer(text=text)
tts.save(audio, "test_output.wav")
print(f"💾 Đã lưu: test_output.wav")

# Liệt kê các giọng có sẵn
print("\n🎙️ Các giọng có sẵn:")
for label, voice_id in tts.list_preset_voices():
    print(f"   - {label} (ID: {voice_id})")

tts.close()
print("\n✅ Hoàn tất!")