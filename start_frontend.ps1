Write-Host "===========================================" -ForegroundColor Cyan
Write-Host " AI Trading Competition - Frontend Startup" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$NPM = Join-Path $ROOT "runtime\node\npm.cmd"
$NODE_DIR = Join-Path $ROOT "runtime\node"
$FRONTEND = Join-Path $ROOT "frontend"

if (-not (Test-Path $NPM)) {
    Write-Host "[ERROR] npm not found at $NPM" -ForegroundColor Red
    exit 1
}

$env:PATH = "$NODE_DIR;$env:PATH"
$env:NODE_TLS_REJECT_UNAUTHORIZED = "0"   # allow self-signed cert for Vite WS proxy

Set-Location $FRONTEND

if (-not (Test-Path "node_modules")) {
    Write-Host "[INFO] Installing npm dependencies..." -ForegroundColor Yellow
    & $NPM install
}

Write-Host "[INFO] Starting React frontend on http://localhost:5173" -ForegroundColor Green
Write-Host ""
& $NPM run dev
