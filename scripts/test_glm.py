import os
import time
from openai import OpenAI

# SỬA LẠI THÔNG TIN CỦA BẠN
API_KEY = os.environ.get("GLM_API_KEY", "")
BASE_URL = "https://api.z.ai/api/paas/v4" # Hoặc https://open.bigmodel.cn/api/paas/v4
MODEL_ID = "glm-4.7-flash" # Thử đổi thành glm-4-flash, glm-4.7-flash, glm-4-plus...

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    timeout=15.0 # Ép timeout 15s để không phải chờ 40s
)

print(f"🚀 Đang gửi request tới {BASE_URL} với model {MODEL_ID}...")
start = time.time()

try:
    response = client.chat.completions.create(
        model=MODEL_ID,
        messages=[{"role": "user", "content": "Chào bạn"}],
        max_tokens=50,
        stream=False # Thử không stream trước để dễ bắt lỗi
    )
    end = time.time()
    print(f"⏱️ Thời gian: {end - start:.2f} giây")
    print(f"📦 Toàn bộ response: {response}")
    print(f"🤖 Trả lời: {response.choices[0].message.content}")
except Exception as e:
    end = time.time()
    print(f"❌ LỖI SAU {end - start:.2f} giây: {type(e).__name__}: {e}")