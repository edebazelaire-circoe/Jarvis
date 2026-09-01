$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PythonExe = $null
$PythonPrefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = "py"
        $PythonPrefix = @("-3.11")
    }
}
if (-not $PythonExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = "python"
    }
}
if (-not $PythonExe) {
    throw "Jarvis V1 requires a working Python 3.11+ interpreter."
}

& $PythonExe @PythonPrefix -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv" }

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e ".[voice,dev]"

if (-not (Test-Path "config\jarvis.toml")) {
    Copy-Item "config\jarvis.example.toml" "config\jarvis.toml"
}

Write-Host ""
Write-Host "Jarvis V1 Python environment is ready."
Write-Host "Next:"
Write-Host '  1. $env:OPENAI_API_KEY="..."'
Write-Host "  2. .\.venv\Scripts\python.exe scripts\bootstrap_third_party.py   # one-time, needs Internet"
Write-Host "  3. .\.venv\Scripts\python.exe -m jarvis health"
Write-Host "  4. .\.venv\Scripts\python.exe scripts\dev_start.py"
Write-Host ""
Write-Host "Voice-only: .\.venv\Scripts\python.exe scripts\dev_start.py --no-board --no-visualizer"
