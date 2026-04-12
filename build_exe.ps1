# ─────────────────────────────────────────────────────────────────────────────
# build_exe.ps1 — Compile launcher_gui.pyw into "Start Trading App.exe"
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   Right-click → "Run with PowerShell"   (or: .\build_exe.ps1)
#
# Output:
#   Start Trading App.exe   — GUI launcher, no console window, no Python needed
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$CONDA  = "C:\Users\gl450\radioconda"
$python = Join-Path $CONDA "python.exe"
$pip    = Join-Path $CONDA "Scripts\pip.exe"
$pyi    = Join-Path $CONDA "Scripts\pyinstaller.exe"

Write-Host ""
Write-Host "════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  AI Trading Competition — Build EXE" -ForegroundColor Cyan
Write-Host "════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── 1. Verify radioconda Python is present ────────────────────────────────────
if (-not (Test-Path $python)) {
    Write-Host "ERROR: radioconda not found at $CONDA" -ForegroundColor Red; exit 1
}
Write-Host "Using Python: $python" -ForegroundColor Gray

# ── 2. Install PyInstaller + Pillow into radioconda ───────────────────────────
Write-Host "Installing PyInstaller + Pillow..." -ForegroundColor Yellow
& $pip install -q --upgrade pyinstaller pillow
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed." -ForegroundColor Red; exit 1
}

# ── 4. Generate icon ─────────────────────────────────────────────────────────
$ico = Join-Path $root "launcher.ico"
Write-Host "Generating icon..." -ForegroundColor Yellow
& $python (Join-Path $root "create_icon.py")

# ── 5. Clean old build artefacts ─────────────────────────────────────────────
$oldExe = Join-Path $root "Start Trading App.exe"
if (Test-Path $oldExe) {
    Remove-Item $oldExe -Force
    Write-Host "Removed old exe." -ForegroundColor Gray
}
foreach ($d in @("dist", "build")) {
    $dp = Join-Path $root $d
    if (Test-Path $dp) { Remove-Item $dp -Recurse -Force }
}

# ── 6. Run PyInstaller ────────────────────────────────────────────────────────
Write-Host "Compiling launcher_gui.pyw via spec file..." -ForegroundColor Yellow
Set-Location $root

$pyiArgs = @(
    "launcher_gui.spec",
    "--clean",
    "--noconfirm"
)

& $pyi @pyiArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: PyInstaller failed." -ForegroundColor Red; exit 1
}

# ── 7. Move exe to root ───────────────────────────────────────────────────────
$built = Join-Path $root "dist\Start Trading App.exe"
if (Test-Path $built) {
    Move-Item $built $root -Force
    Remove-Item (Join-Path $root "dist") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $root "build") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $root "Start Trading App.spec") -Force -ErrorAction SilentlyContinue
}

# ── 8. Result ─────────────────────────────────────────────────────────────────
$final = Join-Path $root "Start Trading App.exe"
if (Test-Path $final) {
    Write-Host ""
    Write-Host "SUCCESS!" -ForegroundColor Green
    Write-Host "  EXE -> $final" -ForegroundColor Green
    Write-Host ""
    Write-Host "Double-click 'Start Trading App.exe' to launch." -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host "Build failed - exe not found." -ForegroundColor Red
    exit 1
}
