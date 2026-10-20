# Essai réel Slice 10 : Core + Control Center isolés (ports 28653/28654), harnais navigateur, arrêt par PID.
$ErrorActionPreference = 'Stop'
$S = 'C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\7314dd51-936a-4614-8684-8f4233075b7c\scratchpad\s10'
$Repo = 'C:\Projects\jarvis\orch10'
$Py = 'C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force "$S\data", "$S\runtime", "$S\shots", "$S\logs" | Out-Null

$env:JARVIS_DATA_ROOT = "$S\data"
$env:JARVIS_RUNTIME_DIR = "$S\runtime"
$env:JARVIS_CORE_PORT = '28653'
$env:JARVIS_UI_PORT = '28654'
$env:JARVIS_VISUALIZER_ENABLED = '0'
$env:JARVIS_OPEN_BROWSER = '0'

$started = @()
try {
  $core = Start-Process -FilePath $Py -ArgumentList '-m', 'jarvis', 'core' -WorkingDirectory $Repo -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$S\logs\core.out" -RedirectStandardError "$S\logs\core.err"
  $started += $core.Id
  $cc = Start-Process -FilePath $Py -ArgumentList '-m', 'jarvis', 'control-center' -WorkingDirectory $Repo -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$S\logs\cc.out" -RedirectStandardError "$S\logs\cc.err"
  $started += $cc.Id
  "PIDs core=$($core.Id) cc=$($cc.Id)"
  $ok = $false
  for ($i = 0; $i -lt 90; $i++) {
    try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:28654/api/subagent-roles'; if ($r.StatusCode -eq 200) { $ok = $true; break } } catch {}
    Start-Sleep -Milliseconds 1000
  }
  if (-not $ok) { throw 'Control Center sandbox not healthy after 90 s' }
  "healthy after $i s"
  & $Py "$S\make_plan_fix.py" "$S/plan.json"
  & node "$Repo\tests\unit\_interaction_mode_browser.mjs" 'http://127.0.0.1:28654/' 'C:\Program Files\Google\Chrome\Application\chrome.exe' "@$S\plan.json" "$S\runtime" | Out-File -Encoding utf8 "$S\browser-result-fix.json"
  "browser exit $LASTEXITCODE"
} finally {
  foreach ($id in $started) { & taskkill.exe /T /F /PID $id 2>&1 | Out-String | Write-Output }
  Start-Sleep -Milliseconds 800
  foreach ($id in $started) { if (Get-Process -Id $id -ErrorAction SilentlyContinue) { "STILL ALIVE $id" } else { "stopped $id" } }
}
