Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " AI Trading Competition - Offline Setup  " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$NPM = "C:\Users\gl450\radioconda\envs\trading\npm.cmd"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

# Check Python 3.12
$pyVersion = python --version 2>&1
if ($pyVersion -notmatch "3\.12") {
    Write-Host "[ERROR] Python 3.12 is required. These wheels were built for Python 3.12." -ForegroundColor Red
    exit 1
}

# Create .env if missing
$ENV_FILE = Join-Path $ROOT ".env"
$ENV_EXAMPLE = Join-Path $ROOT ".env.example"
if (-not (Test-Path $ENV_FILE)) {
    if (Test-Path $ENV_EXAMPLE) {
        Copy-Item $ENV_EXAMPLE $ENV_FILE
        Write-Host "[INFO] Created .env from .env.example" -ForegroundColor Yellow
    } else {
        @"
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
FINNHUB_API_KEY=
"@ | Set-Content $ENV_FILE
        Write-Host "[INFO] Created blank .env - fill in your API keys before running." -ForegroundColor Yellow
    }
    Start-Process notepad $ENV_FILE
    Read-Host "Press Enter after saving .env to continue"
}

# Install Python deps from local packages
Write-Host "[INFO] Installing Python dependencies from local packages..." -ForegroundColor Green
Set-Location (Join-Path $ROOT "backend")
pip install --no-index --find-links packages\ -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Python install failed." -ForegroundColor Red
    exit 1
}
Set-Location $ROOT

# Check node_modules
$NODE_MODULES = Join-Path $ROOT "frontend\node_modules"
if (Test-Path $NODE_MODULES) {
    Write-Host "[OK] node_modules found - no npm install needed." -ForegroundColor Green
} else {
    Write-Host "[WARNING] node_modules missing. Run: cd frontend; & '$NPM' install" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Setup complete!" -ForegroundColor Green
Write-Host " To start: run start_backend.ps1 and start_frontend.ps1" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
