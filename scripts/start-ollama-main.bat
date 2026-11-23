@echo off
REM Ollama Main Instance (Arcee) - Port 11434
REM T?i ?u: Flash Attention + KV Cache Q8

set OLLAMA_HOST=127.0.0.1:11434
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_KV_CACHE_TYPE=q8_0
set OLLAMA_NUM_PARALLEL=1
set OLLAMA_MAX_LOADED_MODELS=1

echo Starting Ollama Main (Arcee) with Flash Attention...
ollama serve
