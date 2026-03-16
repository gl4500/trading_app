@echo off
echo ==========================================
echo  AI Trading Competition - Backend Startup
echo ==========================================

set CONDA_PYTHON=C:\Users\gl450\radioconda\envs\trading\python.exe

cd /d "%~dp0backend"

if not exist "..\\.env" (
    echo [WARN] No .env file found. Copying from .env.example...
    copy "..\\.env.example" "..\.env"
    echo [INFO] Please edit .env with your API keys before starting!
    pause
    exit /b 1
)

if not exist "%CONDA_PYTHON%" (
    echo [ERROR] Conda trading environment not found at %CONDA_PYTHON%
    echo [INFO] Run: conda create -n trading python=3.12
    pause
    exit /b 1
)

echo [INFO] Starting FastAPI backend on http://localhost:8000
echo [INFO] API docs at http://localhost:8000/docs
echo.
"%CONDA_PYTHON%" main.py

pause
