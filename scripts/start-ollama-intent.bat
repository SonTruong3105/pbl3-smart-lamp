@echo off
REM Ollama Intent Router - Port 11437
set OLLAMA_HOST=127.0.0.1:11437
set OLLAMA_MODELS=D:\ollama_models_intent
set OLLAMA_LOG_DIR=D:\ollama_models_intent\logs
set OLLAMA_NUM_PARALLEL=2
set OLLAMA_MAX_LOADED_MODELS=1
ollama serve
