@echo off
echo ==========================================
echo  AI Trading App - Backend Startup
echo ==========================================

set ROOT=%~dp0
set PYTHON=%ROOT%runtime\python\python.exe

cd /d "%ROOT%backend"

if not exist "%ROOT%.env" (
    echo [WARN] No .env file found. Copying from .env.example...
    copy "%ROOT%.env.example" "%ROOT%.env"
    echo [INFO] Edit .env with your API keys, then re-run this script.
    pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo [ERROR] Bundled Python not found at %PYTHON%
    pause
    exit /b 1
)

:: ── Ollama GPU settings ────────────────────────────────────────────────────
:: Force all model layers onto the GPU (RTX 2060, 6 GB VRAM).
:: OLLAMA_NUM_GPU=999  → offload every layer to VRAM (auto-capped to model max)
:: OLLAMA_NUM_THREAD=2 → Ollama uses only 2 CPU threads for non-GPU work,
::                       leaving the remaining cores free for Python data fetching.
:: These must be set BEFORE Ollama starts — restart Ollama if it was already running.
set OLLAMA_NUM_GPU=999
set OLLAMA_NUM_THREAD=2

echo [INFO] Ollama GPU offload: OLLAMA_NUM_GPU=%OLLAMA_NUM_GPU%, OLLAMA_NUM_THREAD=%OLLAMA_NUM_THREAD%
echo [INFO] Starting FastAPI backend on http://localhost:8000
echo [INFO] API docs at http://localhost:8000/docs
echo.
"%PYTHON%" main.py

pause
