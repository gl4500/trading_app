@echo off
REM W3 ensemble daily check-in - double-click this file to run the review.
REM Output stays in the window until you press a key.
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "PYTHONIOENCODING=utf-8"
"%ROOT%\runtime\python\python.exe" "%ROOT%\scripts\w3_review.py" %*
echo.
pause
endlocal
