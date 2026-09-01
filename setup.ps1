$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Prefix = @()
    )

    # A missing py runtime (for example `py -3.11` when only 3.14 is
    # installed) writes to stderr and can become terminating when the
    # caller uses ErrorActionPreference=Stop. Probing must fail soft so we
    # can try the next valid interpreter.
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Executable @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}

$PythonExe = $null
$PythonPrefix = @()

# Prefer `python` because it is the interpreter the user just proved works.
# This also avoids hard-coding a minor version such as 3.11.
if (Get-Command python -ErrorAction SilentlyContinue) {
    if (Test-PythonCandidate -Executable "python") {
        $PythonExe = "python"
    }
}

# Fall back to the Windows Python launcher and ask for any Python 3 runtime.
# `py -3` selects an installed Python 3 version; the probe above enforces
# the actual Jarvis requirement (>= 3.11).
if (-not $PythonExe -and (Get-Command py -ErrorAction SilentlyContinue)) {
    if (Test-PythonCandidate -Executable "py" -Prefix @("-3")) {
        $PythonExe = "py"
        $PythonPrefix = @("-3")
    }
}

if (-not $PythonExe) {
    throw "Jarvis V1 requires a working Python 3.11+ interpreter. Install Python 3.11 or newer, then rerun setup.ps1."
}

$PythonVersion = & $PythonExe @PythonPrefix -c "import sys; print(sys.version.split()[0])"
Write-Host "Using Python $PythonVersion"

& $PythonExe @PythonPrefix -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv" }

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment was created but $VenvPython was not found."
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip" }

& $VenvPython -m pip install -e ".[voice,dev]"
if ($LASTEXITCODE -ne 0) { throw "Failed to install Jarvis dependencies" }

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
