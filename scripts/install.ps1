# ── AWS Harness installer (Windows 11, native) ──────────────────
# PowerShell 5.1+. One command from a fresh machine:
#     .\scripts\install.ps1
# Idempotent: safe to re-run.
$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $PSScriptRoot
Set-Location $RepoDir

function Say($msg)  { Write-Host "» $msg" -ForegroundColor Cyan }
function Die($msg)  { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }

# 1. Python >= 3.11
try { $py = python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null }
catch { $py = $null }
if (-not $py) {
    try { $py = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null }
    catch { $py = $null }
}
if (-not $py) { Die "Python not found — install Python 3.11+ from python.org first" }
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { Die "Python 3.11+ required, found $py" }
Say "Python $py found"

# 2. Install into the user site (no venv needed for a CLI tool)
Say "Installing (pip --user)"
python -m pip install --user -e . -q
if ($LASTEXITCODE -ne 0) { Say "retrying with --break-system-packages"; python -m pip install --user --break-system-packages -e . -q }

# 3. PATH check — pip --user scripts live in %APPDATA%\Python\Scripts
$UserScripts = join-path $env:APPDATA "Python\Python3*\Scripts"
if (-not ($env:PATH -like "*$UserScripts*")) {
    $found = Get-Item $UserScripts -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        Say "Adding $($found.FullName) to your user PATH (new terminals only)"
        [Environment]::SetEnvironmentVariable(
            "PATH",
            [Environment]::GetEnvironmentVariable("PATH", "User") + ";" + $found.FullName,
            "User")
    }
}

# 4. Verify
Say "Verifying…"
try { & harness version }
catch {
    Say "harness not found on PATH yet — open a NEW terminal and run:"
    Say "    harness version"
    Say "(PATH updates apply to new terminals)"
}

Write-Host ""
Write-Host "✓ Installed. Next:" -ForegroundColor Green
Write-Host "  1. Credentials: %USERPROFILE%\.aws\credentials (same format as Linux)"
Write-Host "  2. Config:      %USERPROFILE%\.config\aws-harness\config.yaml"
Write-Host "     (copy from harness_config\templates\config.yaml and edit)"
Write-Host "  3. Verify:      harness whoami ; harness doctor"
Write-Host ""
Write-Host "Docs: docs\user-manual.md (§10b for Windows notes)"
