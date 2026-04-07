@echo off
echo ==========================================
echo  AI Trading App - Launch Both Services
echo ==========================================

set ROOT=%~dp0

if not exist "%ROOT%.env" (
    echo [WARN] No .env file found. Copying from .env.example...
    copy "%ROOT%.env.example" "%ROOT%.env"
    echo [INFO] Edit .env with your API keys, then re-run this script.
    pause
    exit /b 1
)

echo [INFO] Starting backend in a new window...
start "Trading App - Backend" cmd /k "%ROOT%start_backend.bat"

echo [INFO] Waiting 3 seconds for backend to initialise...
timeout /t 3 /nobreak >nul

echo [INFO] Starting frontend in a new window...
start "Trading App - Frontend" cmd /k "%ROOT%start_frontend.bat"

echo.
echo Both services are launching:
echo   Backend  ^>  http://localhost:8000
echo   Frontend ^>  http://localhost:5173
echo.
echo Close this window at any time — each service runs in its own window.
