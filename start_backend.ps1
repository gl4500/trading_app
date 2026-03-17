Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " AI Trading Competition - Backend Startup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$PYTHON = Join-Path $ROOT "runtime\python\python.exe"
$BACKEND = Join-Path $ROOT "backend"
$ENV_FILE = Join-Path $ROOT ".env"
$SITE_PACKAGES = Join-Path $ROOT "site-packages"

if (-not (Test-Path $ENV_FILE)) {
    Write-Host "[WARN] No .env file found. Please create one with your API keys." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $PYTHON)) {
    Write-Host "[ERROR] Python runtime not found at $PYTHON" -ForegroundColor Red
    exit 1
}

# Kill any python.exe process running main.py (previous backend instance)
$existingProcs = Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*main.py*" }
foreach ($proc in $existingProcs) {
    Write-Host "[INFO] Stopping previous backend (PID $($proc.ProcessId))..." -ForegroundColor Yellow
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($existingProcs) { Start-Sleep -Seconds 2 }

$env:PYTHONPATH = $SITE_PACKAGES

# Generate TLS certs if missing
$CERT = Join-Path $ROOT "certs\cert.pem"
if (-not (Test-Path $CERT)) {
    Write-Host "[INFO] Generating TLS certificate for localhost..." -ForegroundColor Yellow
    & $PYTHON (Join-Path $ROOT "gen_certs.py")
}

$PROTOCOL = if (Test-Path $CERT) { "https" } else { "http" }
Write-Host "[INFO] Starting FastAPI backend on ${PROTOCOL}://localhost:8000" -ForegroundColor Green
Write-Host "[INFO] API docs at ${PROTOCOL}://localhost:8000/docs" -ForegroundColor Green
Write-Host ""

Set-Location $BACKEND
& $PYTHON main.py
