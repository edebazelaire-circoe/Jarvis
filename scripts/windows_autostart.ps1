param([ValidateSet('install','remove','status')][string]$Action = 'install')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..
$TaskName = 'Jarvis-v0.2'
$Python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
$Supervisor = Join-Path (Get-Location) 'scripts\supervisor_v2.py'
if ($Action -eq 'remove') {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host 'Jarvis autostart removed.'
    exit 0
}
if ($Action -eq 'status') {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    exit 0
}
if (-not (Test-Path $Python)) { throw "Python venv not found: $Python" }
if (-not (Test-Path $Supervisor)) { throw "Supervisor not found: $Supervisor" }
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
$TaskAction = New-ScheduledTaskAction -Execute $Python -Argument ('"' + $Supervisor + '"') -WorkingDirectory (Get-Location).Path
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $TaskAction -Trigger $Trigger -Principal $Principal -Settings $Settings | Out-Null
Write-Host 'Jarvis autostart installed for the current user session.'
