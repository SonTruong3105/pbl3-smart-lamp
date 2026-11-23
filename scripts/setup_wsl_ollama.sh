#!/bin/bash

echo "======================================================"
echo "  CÀI ĐẶT OLLAMA TRÊN WSL2 (UBUNTU)"
echo "======================================================"

# 1. Cài đặt Ollama
echo "[1/4] Đang tải và cài đặt Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# 2. Cấu hình Service
echo "[2/4] Đang cấu hình Ollama Service..."
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf <<EOT
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
EOT

# 3. Khởi động lại
echo "[3/4] Đang khởi động lại Ollama..."
sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo systemctl enable ollama

# 4. Tải model
echo "[4/4] Đang tải các mô hình AI (quá trình này có thể mất vài phút)..."
ollama pull qwen3.5:4b-q4_K_M
ollama pull qwen3.5:0.8b

echo "======================================================"
echo "✅ HOÀN TẤT! Ollama đã sẵn sàng trên WSL2."
echo "Bây giờ bạn có thể chạy 'python run.py' trên Windows."
echo "======================================================"