@echo off
echo ==========================================
echo  AI Trading Competition - Setup
echo ==========================================

:: Create .env from example if not exists
if not exist ".env" (
    echo [INFO] Creating .env from .env.example...
    copy ".env.example" ".env"
    echo.
    echo [ACTION REQUIRED] Please edit .env with your API keys:
    echo   - ALPACA_API_KEY + ALPACA_SECRET_KEY (paper trading)
    echo   - ANTHROPIC_API_KEY (for ClaudeAgent)
    echo   - OPENAI_API_KEY (for SentimentAgent)
    echo.
    notepad .env
)

:: Backend setup
echo [INFO] Setting up Python backend...
cd backend
pip install -r requirements.txt
cd ..

:: Frontend setup
echo [INFO] Setting up Node.js frontend...
cd frontend
npm install
cd ..

echo.
echo ==========================================
echo  Setup complete!
echo
echo  To start the application:
echo    1. Run start_backend.bat (keep open)
echo    2. Run start_frontend.bat (keep open)
echo    3. Open http://localhost:5173
echo ==========================================
pause
