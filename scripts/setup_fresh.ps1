#Requires -Version 5.1
<#
.SYNOPSIS
    Fresh-install setup for AI Trading App.
    Downloads Python 3.12, Node.js, installs all packages, generates TLS certs,
    and creates .env from template. Run once on a new machine after cloning.

.DESCRIPTION
    Estimated download sizes (first run only):
      Python 3.12.12 installer  ~  28 MB
      Node.js 22 LTS zip        ~  20 MB
      Python packages           ~ 200 MB  (without PyTorch)
      PyTorch CPU               ~ 250 MB  (if selected)
      PyTorch GPU (CUDA 12.4)   ~ 2.5 GB  (if selected)
      npm packages              ~  50 MB
    Total without PyTorch GPU: ~550 MB

.USAGE
    From an elevated (or normal) PowerShell prompt in the repo root:
        .\scripts\setup_fresh.ps1
    Or just double-click setup_fresh.bat which launches this script.
#>

$ErrorActionPreference = "Stop"

# ── Resolve paths ─────────────────────────────────────────────────────────────
$SCRIPTS = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT    = Split-Path -Parent $SCRIPTS
$PYTHON  = "$ROOT\runtime\python\python.exe"
$SITE    = "$ROOT\site-packages"
$TEMP    = "$env:TEMP\trading_app_setup"

# ── Software versions ─────────────────────────────────────────────────────────
$PY_VER   = "3.12.12"
$PY_URL   = "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-amd64.exe"
$NODE_VER = "22.16.0"   # Node.js 22 LTS
$NODE_URL = "https://nodejs.org/dist/v$NODE_VER/node-v$NODE_VER-win-x64.zip"

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [ OK ] $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "  [ .. ] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [ERR] $msg" -ForegroundColor Red; Read-Host "Press Enter to exit"; exit 1 }

function Download-File {
    param($url, $dest, $label)
    Write-Info "Downloading $label..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($url, $dest)
    } catch {
        # Fallback to Invoke-WebRequest (slower but works without .NET WebClient in some configs)
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    }
    if (-not (Test-Path $dest)) { Write-Fail "Download failed: $url" }
    Write-Info "  Downloaded to $dest"
}

# ── Banner ────────────────────────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   AI Trading App  -  Fresh Install" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  This script sets up the full runtime environment on a new machine." -ForegroundColor White
Write-Host "  It will download Python 3.12, Node.js 22, Python packages, and" -ForegroundColor White
Write-Host "  frontend packages from the internet. Needs a working connection." -ForegroundColor White
Write-Host ""
$go = Read-Host "  Continue? [Y/n]"
if ($go -match "^[Nn]") { exit 0 }

New-Item -ItemType Directory -Force -Path $TEMP    | Out-Null
New-Item -ItemType Directory -Force -Path "$ROOT\runtime" | Out-Null
New-Item -ItemType Directory -Force -Path $SITE    | Out-Null

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 1  —  Python 3.12
# ═══════════════════════════════════════════════════════════════════════════════
Write-Step "Python $PY_VER runtime  →  runtime\python\"

if (Test-Path $PYTHON) {
    $ver = & $PYTHON --version 2>&1
    Write-OK "Already present: $ver"
} else {
    $installer = "$TEMP\python-$PY_VER-amd64.exe"
    if (-not (Test-Path $installer)) {
        Download-File $PY_URL $installer "Python $PY_VER installer (~28 MB)"
    }
    Write-Info "Installing Python to runtime\python\  (this takes ~30 seconds)..."
    $pyArgs = "/quiet InstallAllUsers=0 TargetDir=`"$ROOT\runtime\python`" " +
              "PrependPath=0 Include_launcher=0 Include_tcltk=1 Include_pip=1 " +
              "Include_test=0 Include_doc=0"
    $proc = Start-Process -FilePath $installer -ArgumentList $pyArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Fail "Python installer exited with code $($proc.ExitCode). Try running setup_fresh.bat as Administrator."
    }
    if (-not (Test-Path $PYTHON)) {
        Write-Fail "python.exe not found after install — check $ROOT\runtime\python"
    }
    Write-OK "Python $PY_VER installed at runtime\python\"
}

# Upgrade pip silently
Write-Info "Upgrading pip..."
& $PYTHON -m pip install --upgrade pip --quiet 2>&1 | Out-Null

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2  —  Node.js 22 LTS
# ═══════════════════════════════════════════════════════════════════════════════
Write-Step "Node.js $NODE_VER LTS  →  runtime\node\"

if (Test-Path "$ROOT\runtime\node\node.exe") {
    $nodever = & "$ROOT\runtime\node\node.exe" --version 2>&1
    Write-OK "Already present: Node.js $nodever"
} else {
    $nodeZip     = "$TEMP\node-$NODE_VER-win-x64.zip"
    $nodeExtract = "$TEMP\node_extract"
    if (-not (Test-Path $nodeZip)) {
        Download-File $NODE_URL $nodeZip "Node.js $NODE_VER zip (~20 MB)"
    }
    Write-Info "Extracting Node.js..."
    if (Test-Path $nodeExtract) { Remove-Item $nodeExtract -Recurse -Force }
    Expand-Archive -Path $nodeZip -DestinationPath $nodeExtract -Force
    $extracted = Get-ChildItem $nodeExtract -Directory | Select-Object -First 1
    if (-not $extracted) { Write-Fail "Node.js zip contained no directory — re-run setup to retry." }
    Move-Item $extracted.FullName "$ROOT\runtime\node"
    if (-not (Test-Path "$ROOT\runtime\node\node.exe")) {
        Write-Fail "node.exe not found after extraction"
    }
    Write-OK "Node.js $NODE_VER installed at runtime\node\"
}

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3  —  Python packages
# ═══════════════════════════════════════════════════════════════════════════════
Write-Step "Python packages  →  site-packages\"

# ── 3a. PyTorch (handled separately — GPU vs CPU choice matters for size) ─────
$torchPresent = (Test-Path "$ROOT\runtime\python\Lib\site-packages\torch") -or (Test-Path "$SITE\torch")

if ($torchPresent) {
    Write-OK "PyTorch already installed"
} else {
    Write-Host ""
    Write-Host "  PyTorch is used by the CNN Reasoning Agent for signal weighting." -ForegroundColor White
    Write-Host ""
    Write-Host "  CPU version   ~  250 MB — works on any machine, training is slower" -ForegroundColor White
    Write-Host "  GPU version   ~ 2.5 GB  — requires NVIDIA GPU + CUDA 12.4 drivers" -ForegroundColor White
    Write-Host "  Skip for now  — app starts without it; CNN agent runs in surrogate mode" -ForegroundColor White
    Write-Host ""
    $torchChoice = Read-Host "  Install PyTorch? [C]PU / [G]PU / [S]kip  (default: C)"

    if ($torchChoice -match "^[Gg]") {
        Write-Info "Installing PyTorch GPU (CUDA 12.4) — ~2.5 GB download..."
        & $PYTHON -m pip install torch `
            --index-url https://download.pytorch.org/whl/cu124 `
            --quiet
        if ($LASTEXITCODE -ne 0) { Write-Fail "PyTorch GPU install failed" }
        Write-OK "PyTorch (GPU/CUDA 12.4) installed"
    } elseif ($torchChoice -match "^[Ss]") {
        Write-Info "Skipping PyTorch — CNN agent will run in surrogate (rule-based) mode"
    } else {
        Write-Info "Installing PyTorch (CPU-only) — ~250 MB download..."
        & $PYTHON -m pip install torch `
            --index-url https://download.pytorch.org/whl/cpu `
            --quiet
        if ($LASTEXITCODE -ne 0) { Write-Fail "PyTorch CPU install failed" }
        Write-OK "PyTorch (CPU) installed"
    }
}

# ── 3b. All other packages ────────────────────────────────────────────────────
Write-Info "Installing remaining packages (requirements.txt, excluding torch)..."

# Write a temp requirements file with torch line removed
$filteredReq = "$TEMP\requirements_notorch.txt"
Get-Content "$ROOT\backend\requirements.txt" |
    Where-Object { $_ -notmatch "^\s*torch\b" } |
    Set-Content $filteredReq

$env:PYTHONPATH = $SITE
& $PYTHON -m pip install -r $filteredReq --target $SITE --quiet
if ($LASTEXITCODE -ne 0) { Write-Fail "Package installation failed — see errors above." }
Write-OK "All packages installed to site-packages\"

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 4  —  Frontend packages (npm install)
# ═══════════════════════════════════════════════════════════════════════════════
Write-Step "Frontend packages  →  frontend\node_modules\"

if (Test-Path "$ROOT\frontend\node_modules") {
    Write-OK "node_modules already present"
} else {
    Write-Info "Running npm install (~50 MB)..."
    $env:PATH = "$ROOT\runtime\node;$env:PATH"
    Push-Location "$ROOT\frontend"
    try {
        & "$ROOT\runtime\node\npm.cmd" install --silent
        if ($LASTEXITCODE -ne 0) { Write-Fail "npm install failed" }
    } finally {
        Pop-Location
    }
    Write-OK "Frontend packages installed"
}

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 5  —  .env configuration
# ═══════════════════════════════════════════════════════════════════════════════
Write-Step ".env  —  API keys and app configuration"

$envFile = "$ROOT\.env"
if (Test-Path $envFile) {
    Write-OK ".env already exists — not overwriting"
} else {
    Copy-Item "$ROOT\.env.example" $envFile

    # Auto-generate SESSION_SECRET so auth works out of the box
    $secret = & $PYTHON -c "import secrets; print(secrets.token_hex(32))"
    $content = Get-Content $envFile -Raw
    $content = $content -replace "SESSION_SECRET=.*", "SESSION_SECRET=$secret"
    Set-Content $envFile $content

    Write-OK ".env created from template (SESSION_SECRET auto-generated)"
    Write-Host ""
    Write-Host "  ACTION REQUIRED:" -ForegroundColor Yellow
    Write-Host "  Fill in your API keys in .env before starting the app." -ForegroundColor Yellow
    Write-Host "  Required:  ALPACA_API_KEY + ALPACA_SECRET_KEY (paper trading keys)" -ForegroundColor Yellow
    Write-Host "  Optional:  ANTHROPIC / OPENAI / GEMINI keys (or use Ollama offline)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Opening .env in Notepad..." -ForegroundColor Yellow
    Start-Process notepad $envFile
    Read-Host "  Press Enter after saving .env to continue"
}

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 6  —  TLS certificates
# ═══════════════════════════════════════════════════════════════════════════════
Write-Step "TLS certificates  →  certs\"

if (Test-Path "$ROOT\certs\cert.pem") {
    Write-OK "Certificates already present"
} else {
    Write-Info "Generating self-signed TLS certificate for localhost..."
    $env:PYTHONPATH = $SITE
    & $PYTHON "$ROOT\scripts\gen_certs.py"
    if ($LASTEXITCODE -ne 0) { Write-Fail "Certificate generation failed" }
    Write-OK "Certificates generated in certs\"
    Write-Host ""
    Write-Host "  NOTE: Your browser will warn about this self-signed certificate." -ForegroundColor Yellow
    Write-Host "  Click 'Advanced' → 'Proceed to localhost' to trust it the first time." -ForegroundColor Yellow
}

# ═══════════════════════════════════════════════════════════════════════════════
#  DONE
# ═══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "   Setup complete!  Everything is ready." -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  To launch the app:" -ForegroundColor White
Write-Host "    Double-click  'Start Trading App.exe'  in the repo root" -ForegroundColor White
Write-Host ""
Write-Host "  Or start manually (two terminals):" -ForegroundColor White
Write-Host "    Terminal 1:  .\start_backend.ps1" -ForegroundColor White
Write-Host "    Terminal 2:  .\start_frontend.ps1" -ForegroundColor White
Write-Host "    Browser:     https://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "  If the browser shows a certificate warning:" -ForegroundColor White
Write-Host "    Click 'Advanced' then 'Proceed to localhost (unsafe)'" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to close"
