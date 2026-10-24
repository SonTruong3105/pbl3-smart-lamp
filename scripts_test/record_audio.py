import serial
import wave
import time

SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 115200 

try:
    print(f"Đang kết nối tới {SERIAL_PORT}...")
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
    time.sleep(2)
    ser.reset_input_buffer()
    
    print("Gửi lệnh 'R'...")
    ser.write(b'R')
    
    print("Đợi tín hiệu START_RECORDING...")
    buffer = b""
    while True:
        char = ser.read(1)
        if not char: continue
        buffer += char
        if b"START_RECORDING" in buffer:
            print("🎙️ Đã nhận tín hiệu! Bắt đầu ghi âm 2 kênh (Stereo)...")
            break
            
    # 5 giây * 16000 samples * 2 kênh * 2 bytes = 320,000 bytes
    target_size = 16000 * 2 * 2 * 5
    raw_data = bytearray()
    
    start_time = time.time()
    # Vòng lặp có giới hạn thời gian (tối đa 15 giây) để chống treo
    while len(raw_data) < target_size and (time.time() - start_time) < 15:
        chunk = ser.read(2048)
        if chunk:
            raw_data.extend(chunk)
            
    if len(raw_data) >= target_size:
        raw_data = raw_data[:target_size]
        with wave.open('test_2mic.wav', 'wb') as wf:
            wf.setnchannels(2)      # 2 kênh
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(raw_data)
        print(f"✅ Đã lưu file 'test_2mic.wav' thành công!")
    else:
        print(f"❌ Lỗi: Chỉ nhận được {len(raw_data)}/{target_size} bytes. (Bị ngắt quãng)")
        
except Exception as e:
    print(f"Lỗi: {e}")
finally:
    try: ser.close()
    except: pass