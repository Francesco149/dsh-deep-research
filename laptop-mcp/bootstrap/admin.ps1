# computer-use bootstrap, stage 2 (elevated). Stage 1 sets $TargetUser, $TargetSid, $TargetProfile,
# $TargetIsAdmin and $Server, then runs this with:  iex (irm "$Server/admin.ps1")
# The elevated user may be another account (UAC over the shoulder), so nothing here reads HKCU or
# $env:USERPROFILE: per-user work happened in stage 1. Every step is safe to re-run.
$ErrorActionPreference = 'Stop'
$PubKeys = @'
{{PUBKEYS}}
'@
$Lan = '{{LAN}}'
$SshDir = Join-Path $env:ProgramData 'ssh'
$LogDir = Join-Path $env:ProgramData 'computer-use'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Start-Transcript -Path (Join-Path $LogDir ("bootstrap-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))) | Out-Null

function Step([string]$Msg) { Write-Host ''; Write-Host "==> $Msg" -ForegroundColor Cyan }

function Send-Report([string]$Stage, $Data) {
    try {
        $json = $Data | ConvertTo-Json -Depth 6 -Compress
        Invoke-RestMethod -Method Post -Uri "$Server/report/$Stage" -TimeoutSec 15 `
            -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json)) | Out-Null
    } catch { Write-Host "  (could not report to ${Server}: $_)" -ForegroundColor DarkGray }
}

# Appends the keys a file lacks and locks it down the way sshd's StrictModes wants it.
function Add-Keys([string]$Path, [string[]]$Grants) {
    $dir = Split-Path $Path
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $have = if (Test-Path $Path) { Get-Content $Path } else { @() }
    $add = $PubKeys -split "`r?`n" | Where-Object { $_ -and ($have -notcontains $_) }
    if ($add) { [IO.File]::AppendAllText($Path, (($add -join "`n") + "`n")) }
    $icacls = @($Path, '/inheritance:r') + ($Grants | ForEach-Object { '/grant', "*${_}:F" })
    & icacls.exe @icacls | Out-Null
    if ($LASTEXITCODE) { throw "icacls failed on $Path" }
    Write-Host "  $Path ($(@($add).Count) key(s) added)"
}

try {
    Write-Host 'computer-use bootstrap: stage 2 (administrator)' -ForegroundColor Cyan
    Write-Host "  for $TargetUser, elevated as $env:USERNAME"

    Step 'System facts'
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $sys = @{
        os = $os.Caption; version = $os.Version; build = $os.BuildNumber; os_language = $os.OSLanguage
        model = "$($cs.Manufacturer) $($cs.Model)"; ram_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
        gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {
            "$($_.Name) $($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)" })
        battery = [bool](Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
        users = @(Get-LocalUser | ForEach-Object { "$($_.Name) enabled=$($_.Enabled)" })
        elevated_as = $env:USERNAME
        power_states = @(powercfg /a)
    }
    Send-Report 'sysinfo' $sys
    Write-Host "  $($sys.model), $($sys.os) build $($sys.build), $($sys.ram_gb) GB"

    Step 'OpenSSH Server'
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
        $cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*' | Select-Object -First 1
        try {
            Write-Host "  installing $($cap.Name) from Windows Update (can take a few minutes)"
            Add-WindowsCapability -Online -Name $cap.Name | Out-Null
        } catch {
            Write-Host "  Windows capability failed ($_), trying winget" -ForegroundColor Yellow
            winget install --id Microsoft.OpenSSH.Preview -e --source winget --silent `
                --accept-package-agreements --accept-source-agreements
        }
    }
    $svc = Get-Service sshd
    Set-Service sshd -StartupType Automatic
    if ($svc.Status -ne 'Running') { Start-Service sshd }  # the first start writes host keys + sshd_config
    $cfgPath = Join-Path $SshDir 'sshd_config'
    $cfg = [IO.File]::ReadAllText($cfgPath)
    if ($cfg -notmatch '# computer-use bootstrap') {
        # Before any Match block, where first-match settings apply to everyone.
        $head = "# computer-use bootstrap: keys only`nPasswordAuthentication no`nPubkeyAuthentication yes`n`n"
        [IO.File]::WriteAllText($cfgPath, $head + $cfg)
    }
    New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
    New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -PropertyType String -Force `
        -Value "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" | Out-Null
    Write-Host '  keys only, PowerShell as the login shell'

    Step "Authorized keys for $TargetUser"
    Add-Keys (Join-Path $TargetProfile '.ssh\authorized_keys') @($TargetSid, 'S-1-5-18', 'S-1-5-32-544')
    if ($TargetIsAdmin) {
        # sshd reads only this file for members of Administrators.
        Add-Keys (Join-Path $SshDir 'administrators_authorized_keys') @('S-1-5-18', 'S-1-5-32-544')
    }
    Restart-Service sshd

    Step "Firewall: ssh from $Lan only"
    Get-NetFirewallRule -Name 'computer-use-sshd' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -Name 'computer-use-sshd' -DisplayName 'OpenSSH Server (lab LAN only)' `
        -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -Profile Any -RemoteAddress $Lan | Out-Null
    # The rule Windows adds with the capability allows any address; narrow it to the LAN too.
    Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue |
        Set-NetFirewallRule -RemoteAddress $Lan

    Step 'Power: never sleep on AC, lid does nothing on AC, no password on wake'
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
    powercfg /setacvalueindex SCHEME_CURRENT SUB_NONE CONSOLELOCK 0
    powercfg /setactive SCHEME_CURRENT
    Write-Host '  (the display still turns off when idle; battery settings are unchanged)'

    Step 'Check'
    $listen = [bool](Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue)
    $done = @{
        sshd = (Get-Service sshd).Status.ToString()
        listening = $listen
        host_keys = @(Get-ChildItem $SshDir -Filter 'ssh_host_*_key.pub' | ForEach-Object { (Get-Content $_.FullName -Raw).Trim() })
        addresses = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -notlike '127.*' | ForEach-Object { "$($_.InterfaceAlias) $($_.IPAddress)" })
        networks = @(Get-NetConnectionProfile | ForEach-Object { "$($_.Name) $($_.NetworkCategory)" })
        admin_keys = [bool]$TargetIsAdmin
    }
    Send-Report 'done' $done
    if (-not $listen) { throw 'sshd is not listening on port 22' }
    Write-Host ''
    Write-Host 'ALL DONE. Leave the laptop signed in as the agent account, plugged in, lid open.' -ForegroundColor Green
} catch {
    Write-Host ''
    Write-Host "FAILED: $_" -ForegroundColor Red
    Send-Report 'error' @{ stage = 2; error = "$_"; where = $_.ScriptStackTrace }
}
Stop-Transcript | Out-Null
Read-Host 'Press Enter to close'
