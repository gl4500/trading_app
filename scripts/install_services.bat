@echo off
setlocal EnableDelayedExpansion

echo ==========================================
echo  AI Trading App - NSSM Service Installer
echo ==========================================
echo.

:: ── Auto-elevate to admin ────────────────────────────────────────────────────
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [INFO] Requesting administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && \"%~f0\"' -Verb RunAs"
    exit /b
)

:: ── Locate NSSM ────────────────────────────────────────────────────────────
set NSSM=
where nssm >nul 2>&1
if %errorLevel% equ 0 (
    set NSSM=nssm
) else if exist "%~dp0nssm.exe" (
    set NSSM=%~dp0nssm.exe
) else (
    echo [ERROR] nssm.exe not found.
    echo.
    echo  Download NSSM from: https://nssm.cc/download
    echo  Place nssm.exe in:  %~dp0
    echo  Then re-run this script.
    echo.
    pause
    exit /b 1
)
echo [INFO] Using NSSM: %NSSM%

:: ── Paths ──────────────────────────────────────────────────────────────────
:: scripts\ is one level below the project root
for %%I in ("%~dp0..") do set ROOT=%%~fI

set PYTHON=%ROOT%\runtime\python\python.exe
set NODE=%ROOT%\runtime\node\node.exe
set NPM_CMD=%ROOT%\runtime\node\npm.cmd
set BACKEND_DIR=%ROOT%\backend
set FRONTEND_DIR=%ROOT%\frontend
set LOG_DIR=%ROOT%\backend\logs

set BACKEND_SVC=TradingAppBackend
set FRONTEND_SVC=TradingAppFrontend

:: ── Validate paths ─────────────────────────────────────────────────────────
if not exist "%PYTHON%" (
    echo [ERROR] Bundled Python not found: %PYTHON%
    pause
    exit /b 1
)
if not exist "%BACKEND_DIR%\main.py" (
    echo [ERROR] main.py not found in: %BACKEND_DIR%
    pause
    exit /b 1
)
if not exist "%ROOT%\.env" (
    echo [WARN] .env not found at %ROOT%\.env — backend will use defaults.
)

:: ── Ensure log directory exists ────────────────────────────────────────────
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: ══════════════════════════════════════════════════════════════════════════
:: BACKEND SERVICE
:: ══════════════════════════════════════════════════════════════════════════
echo.
echo [INFO] Installing backend service: %BACKEND_SVC%

:: Remove existing service if present
%NSSM% status %BACKEND_SVC% >nul 2>&1
if %errorLevel% equ 0 (
    echo [INFO] Removing existing %BACKEND_SVC% service...
    %NSSM% stop %BACKEND_SVC% >nul 2>&1
    %NSSM% remove %BACKEND_SVC% confirm >nul 2>&1
)

%NSSM% install %BACKEND_SVC% "%PYTHON%" "main.py"
%NSSM% set %BACKEND_SVC% AppDirectory       "%BACKEND_DIR%"
%NSSM% set %BACKEND_SVC% DisplayName        "AI Trading App - Backend"
%NSSM% set %BACKEND_SVC% Description        "FastAPI trading backend with AI agents (port 8000)"
%NSSM% set %BACKEND_SVC% Start              SERVICE_AUTO_START

:: Ollama GPU env vars + PYTHONPATH for self-contained runtime
%NSSM% set %BACKEND_SVC% AppEnvironmentExtra "PYTHONPATH=%ROOT%\site-packages" "OLLAMA_NUM_GPU=999" "OLLAMA_NUM_THREAD=2"

:: Stdout / stderr logs (NSSM rotates at 10 MB)
%NSSM% set %BACKEND_SVC% AppStdout          "%LOG_DIR%\backend_stdout.log"
%NSSM% set %BACKEND_SVC% AppStderr          "%LOG_DIR%\backend_stderr.log"
%NSSM% set %BACKEND_SVC% AppStdoutCreationDisposition 4
%NSSM% set %BACKEND_SVC% AppStderrCreationDisposition 4
%NSSM% set %BACKEND_SVC% AppRotateFiles     1
%NSSM% set %BACKEND_SVC% AppRotateBytes     10485760

:: Restart on any non-zero exit; wait 5 s before restarting
%NSSM% set %BACKEND_SVC% AppExit            Default Restart
%NSSM% set %BACKEND_SVC% AppRestartDelay    5000

echo [OK] Backend service installed.

:: ══════════════════════════════════════════════════════════════════════════
:: FRONTEND SERVICE
:: ══════════════════════════════════════════════════════════════════════════
echo.
echo [INFO] Installing frontend service: %FRONTEND_SVC%

if not exist "%NODE%" (
    echo [WARN] Bundled Node not found at %NODE% — skipping frontend service.
    goto :start_services
)
if not exist "%FRONTEND_DIR%\package.json" (
    echo [WARN] frontend\package.json not found — skipping frontend service.
    goto :start_services
)

:: Remove existing service if present
%NSSM% status %FRONTEND_SVC% >nul 2>&1
if %errorLevel% equ 0 (
    echo [INFO] Removing existing %FRONTEND_SVC% service...
    %NSSM% stop %FRONTEND_SVC% >nul 2>&1
    %NSSM% remove %FRONTEND_SVC% confirm >nul 2>&1
)

:: npm.cmd is a batch file; run it via cmd.exe
%NSSM% install %FRONTEND_SVC% "cmd.exe" "/c \"%NPM_CMD%\" run dev"
%NSSM% set %FRONTEND_SVC% AppDirectory       "%FRONTEND_DIR%"
%NSSM% set %FRONTEND_SVC% DisplayName        "AI Trading App - Frontend"
%NSSM% set %FRONTEND_SVC% Description        "React/Vite frontend dev server (port 5173)"
%NSSM% set %FRONTEND_SVC% Start              SERVICE_AUTO_START

%NSSM% set %FRONTEND_SVC% AppStdout          "%LOG_DIR%\frontend_stdout.log"
%NSSM% set %FRONTEND_SVC% AppStderr          "%LOG_DIR%\frontend_stderr.log"
%NSSM% set %FRONTEND_SVC% AppStdoutCreationDisposition 4
%NSSM% set %FRONTEND_SVC% AppStderrCreationDisposition 4
%NSSM% set %FRONTEND_SVC% AppRotateFiles     1
%NSSM% set %FRONTEND_SVC% AppRotateBytes     10485760

%NSSM% set %FRONTEND_SVC% AppExit            Default Restart
%NSSM% set %FRONTEND_SVC% AppRestartDelay    5000

echo [OK] Frontend service installed.

:: ══════════════════════════════════════════════════════════════════════════
:start_services
:: ══════════════════════════════════════════════════════════════════════════
echo.
echo [INFO] Starting services...
%NSSM% start %BACKEND_SVC%
%NSSM% status %BACKEND_SVC%

%NSSM% status %FRONTEND_SVC% >nul 2>&1
if %errorLevel% equ 0 (
    %NSSM% start %FRONTEND_SVC%
    %NSSM% status %FRONTEND_SVC%
)

echo.
echo ==========================================
echo  Services installed and started.
echo.
echo  Backend:  http://localhost:8000
echo  Frontend: http://localhost:5173
echo  API docs: http://localhost:8000/docs
echo.
echo  Both services start automatically on
echo  Windows boot and restart on crash.
echo.
echo  To manage: services.msc
echo  To remove: uninstall_services.bat
echo ==========================================
pause
