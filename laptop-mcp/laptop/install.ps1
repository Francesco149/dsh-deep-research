# Installs or updates deskd for the signed-in agent account. Run over ssh as the agent account, from the
# directory bin/cu deploy copied this folder to. Safe to re-run.
$ErrorActionPreference = 'Stop'
$Home_ = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
Set-Location $Home_
uv sync --quiet --python 3.13
if ($LASTEXITCODE) { throw 'uv sync failed' }

# sshd sessions are session 0 and cannot touch the desktop: deskd runs as an interactive task
# in the agent account's console session, at logon and whenever bin/cu starts it. A second trigger fires every
# minute, from now on, indefinitely; the task runs only while the agent account is signed in, and with IgnoreNew it does
# nothing while deskd runs, so a deskd that died comes back within a minute (RestartOnFailure does not
# do that, and a repetition on the logon trigger only starts at the next logon: both tested 2026-10-19).
# deskd starts the agent Chrome itself when it starts.
$task = 'computer-use-deskd'
$action = New-ScheduledTaskAction -Execute (Join-Path $Home_ '.venv\Scripts\pythonw.exe') `
    -Argument ('"{0}"' -f (Join-Path $Home_ 'deskd.py')) -WorkingDirectory $Home_
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$trigger = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))
)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object CommandLine -like '*deskd.py*' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName $task
for ($i = 0; $i -lt 20 -and -not (Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue); $i++) {
    Start-Sleep -Milliseconds 500
}
if (-not (Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue)) {
    throw 'deskd did not start: see state\deskd.log and Task Scheduler history'
}
Write-Output 'deskd running'
