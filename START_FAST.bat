@echo off
chcp 65001 >nul
title Xiaozhi Fast Boot (Preload + Lifecycle)
cd /d "%~dp0"

echo ======================================================
echo   XIAOZHI - NAP SAN MODEL (TU DONG DON DEP KHI TAT)
echo ======================================================
echo.

echo [1/3] Kiem tra Ollama...
netstat -ano | findstr :11434 >nul
if %errorlevel% neq 0 (
    echo    - Chua chay. Dang bat...
    set OLLAMA_KEEP_ALIVE=-1
    set OLLAMA_MAX_LOADED_MODELS=1
    set OLLAMA_FLASH_ATTENTION=1
    set OLLAMA_KV_CACHE_TYPE=q8_0
    start "Ollama" /B ollama serve
    timeout /t 3 /nobreak >nul
) else (
    echo    - Ollama da chay san.
)
echo.

echo [2/3] Dang bat Server Xiaozhi (se tu dong nap model)...
call venv\Scripts\activate
python run.py

:: Khi python thoat, run.py se tu dong unload models
echo.
echo Da tat Server. VRAM da duoc giai phong.
pause