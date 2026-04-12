@echo off
:: ============================================================
:: run_security_tests.bat — Full security test suite
::
:: Runs test_security.py (25 tests) against the live FastAPI app.
:: Takes ~2-3 min due to PyTorch + pandas_ta imports.
::
:: Run before merging any branch to main.
:: ============================================================
:: scripts\ is one level below the project root
for %%I in ("%~dp0..") do set REPO=%%~fI\
set PYTHON=%REPO%runtime\python\python.exe
set PYTHONPATH=%REPO%site-packages

echo.
echo === Security Test Suite ===
echo.

cd /d "%REPO%backend"

"%PYTHON%" -m unittest tests.test_security -v 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [FAIL] Security tests failed. Fix before merging to main.
    echo.
    exit /b 1
)

echo.
echo [OK] All security tests passed.
echo.
