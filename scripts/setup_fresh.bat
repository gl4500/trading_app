@echo off
:: ================================================================
::  AI Trading App - Fresh Install Launcher
::  Double-click this file to run the automated setup.
:: ================================================================
title AI Trading App - Setup

echo.
echo  Launching setup script...
echo  If Windows blocks it, right-click and choose "Run as administrator"
echo.

:: Launch PowerShell with execution policy bypass so the script
:: runs without needing to change system-wide policy settings.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_fresh.ps1"

if errorlevel 1 (
    echo.
    echo  [ERROR] Setup did not complete. See messages above.
    pause
)
