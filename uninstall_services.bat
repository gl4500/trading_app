@echo off
setlocal

echo ==========================================
echo  AI Trading App - NSSM Service Removal
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
    echo [ERROR] nssm.exe not found. Cannot remove services automatically.
    echo         Open services.msc and stop/delete TradingAppBackend and TradingAppFrontend manually.
    pause
    exit /b 1
)

set BACKEND_SVC=TradingAppBackend
set FRONTEND_SVC=TradingAppFrontend

echo [INFO] Stopping and removing %BACKEND_SVC%...
%NSSM% stop %BACKEND_SVC% >nul 2>&1
%NSSM% remove %BACKEND_SVC% confirm
if %errorLevel% equ 0 (
    echo [OK] %BACKEND_SVC% removed.
) else (
    echo [WARN] %BACKEND_SVC% not found or already removed.
)

echo.
echo [INFO] Stopping and removing %FRONTEND_SVC%...
%NSSM% stop %FRONTEND_SVC% >nul 2>&1
%NSSM% remove %FRONTEND_SVC% confirm
if %errorLevel% equ 0 (
    echo [OK] %FRONTEND_SVC% removed.
) else (
    echo [WARN] %FRONTEND_SVC% not found or already removed.
)

echo.
echo [INFO] Services removed. The app will no longer start on boot.
pause
