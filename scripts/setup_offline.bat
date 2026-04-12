@echo off
echo ==========================================
echo  AI Trading Competition - Offline Setup
echo ==========================================

:: Check for Python 3.12 (required - wheels are built for cp312)
python --version 2>nul | findstr "3.12" >nul
if errorlevel 1 (
    echo [ERROR] Python 3.12 is required. These wheels were built for Python 3.12.
    echo         Download from: https://www.python.org/downloads/release/python-3121/
    pause
    exit /b 1
)

:: Create .env from example if not exists
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] Creating .env from .env.example...
        copy ".env.example" ".env"
    ) else (
        echo [INFO] Creating blank .env file...
        echo # Add your API keys here> .env
        echo ALPACA_API_KEY=>> .env
        echo ALPACA_SECRET_KEY=>> .env
        echo ANTHROPIC_API_KEY=>> .env
        echo OPENAI_API_KEY=>> .env
        echo FINNHUB_API_KEY=>> .env
    )
    echo.
    echo [ACTION REQUIRED] Please edit .env with your API keys before running the app.
    echo.
    notepad .env
)

:: Backend - install from local packages folder (no internet needed)
echo [INFO] Installing Python backend dependencies from local packages...
cd backend
pip install --no-index --find-links packages\ -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Python install failed. See above for details.
    cd ..
    pause
    exit /b 1
)
cd ..

:: Frontend - node_modules is already included, just verify
echo [INFO] Checking frontend dependencies...
if exist "frontend\node_modules" (
    echo [OK] node_modules found - no npm install needed.
) else (
    echo [WARNING] node_modules missing. Run: cd frontend && npm install
)

echo.
echo ==========================================
echo  Setup complete!
echo
echo  To start the application:
echo    1. Run start_backend.bat  (keep open)
echo    2. Run start_frontend.bat (keep open)
echo    3. Open http://localhost:5173
echo ==========================================
pause
