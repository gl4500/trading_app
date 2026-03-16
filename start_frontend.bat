@echo off
echo ==========================================
echo  AI Trading Competition - Frontend Startup
echo ==========================================

set CONDA_BIN=C:\Users\gl450\radioconda\envs\trading
set PATH=%CONDA_BIN%;%PATH%

cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo [INFO] Installing npm dependencies...
    npm install
)

echo [INFO] Starting React frontend on http://localhost:5173
echo.
npm run dev

pause
