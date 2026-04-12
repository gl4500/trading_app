@echo off
echo ==========================================
echo  AI Trading App - Frontend Startup
echo ==========================================

set ROOT=%~dp0
set NODE=%ROOT%runtime\node\node.exe
set NPM=%ROOT%runtime\node\npm.cmd

cd /d "%ROOT%frontend"

if not exist "%NODE%" (
    echo [ERROR] Bundled Node not found at %NODE%
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo [INFO] Installing npm dependencies...
    "%NPM%" install
)

echo [INFO] Starting React frontend on http://localhost:5173
echo.
"%NPM%" run dev

pause
