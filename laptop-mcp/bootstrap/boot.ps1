# computer-use bootstrap, stage 1. Runs as the agent account ({{AGENT_USER}}) in its desktop session,
# started from Win+R:  powershell irm {{SERVER}}|iex
# Per-user settings and session facts here; machine-wide work in stage 2 (admin.ps1, behind UAC).
$ErrorActionPreference = 'Stop'
$Server = '{{SERVER}}'
$Expected = '{{AGENT_USER}}'

function Send-Report([string]$Stage, $Data) {
    try {
        $json = $Data | ConvertTo-Json -Depth 6 -Compress
        Invoke-RestMethod -Method Post -Uri "$Server/report/$Stage" -TimeoutSec 15 `
            -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json)) | Out-Null
    } catch { Write-Host "  (could not report to ${Server}: $_)" -ForegroundColor DarkGray }
}

function Get-FileVersion([string]$Path) {
    if (Test-Path $Path) { (Get-Item $Path).VersionInfo.ProductVersion } else { $null }
}

Write-Host ''
Write-Host 'computer-use bootstrap: stage 1 (as the agent account)' -ForegroundColor Cyan

try {
    if ($env:USERNAME -ne $Expected) {
        Write-Host "Signed in as '$env:USERNAME', not '$Expected'." -ForegroundColor Yellow
        Write-Host "Switch user to $Expected and run the same line again." -ForegroundColor Yellow
        Send-Report 'wrong-user' @{ user = $env:USERNAME }
        Read-Host 'Press Enter to close'
        return
    }

    # The desktop agents drive must never blank into a locked screen.
    $desk = 'HKCU:\Control Panel\Desktop'
    Set-ItemProperty $desk -Name ScreenSaveActive -Value '0'
    Set-ItemProperty $desk -Name ScreenSaverIsSecure -Value '0'

    # whoami lists Administrators even as UAC's deny-only group; SIDs read the same in any locale.
    $isAdmin = [bool]((whoami /groups) -match 'S-1-5-32-544')
    Add-Type -AssemblyName System.Windows.Forms
    $screens = [System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
        @{ name = $_.DeviceName; primary = $_.Primary; bounds = "$($_.Bounds.Width)x$($_.Bounds.Height)" }
    }
    $metrics = Get-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -ErrorAction SilentlyContinue
    $pf = ${env:ProgramFiles}; $pf86 = ${env:ProgramFiles(x86)}; $local = $env:LOCALAPPDATA
    $facts = @{
        user = $env:USERNAME
        sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        profile = $env:USERPROFILE
        admin_member = $isAdmin
        session = (Get-Process -Id $PID).SessionId
        screens = @($screens)
        applied_dpi = $metrics.AppliedDPI
        culture = (Get-Culture).Name
        ui_culture = (Get-UICulture).Name
        browsers = @{
            edge = Get-FileVersion "$pf86\Microsoft\Edge\Application\msedge.exe"
            chrome = (Get-FileVersion "$pf\Google\Chrome\Application\chrome.exe"), (Get-FileVersion "$local\Google\Chrome\Application\chrome.exe") | Where-Object { $_ } | Select-Object -First 1
            firefox = Get-FileVersion "$pf\Mozilla Firefox\firefox.exe"
        }
        winget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
        python = [bool](Get-Command python -ErrorAction SilentlyContinue)
        ps = $PSVersionTable.PSVersion.ToString()
    }
    Send-Report 'user' $facts
    Write-Host "  user $($facts.user), admin group: $isAdmin, session $($facts.session)"

    Write-Host ''
    Write-Host 'Stage 2 needs administrator rights: answer the UAC prompt.' -ForegroundColor Cyan
    $stage2 = "`$TargetUser='$($facts.user)'; `$TargetSid='$($facts.sid)'; `$TargetProfile='$($facts.profile)'; " +
        "`$TargetIsAdmin=`$$isAdmin; `$Server='$Server'; iex (irm '$Server/admin.ps1')"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($stage2))
    try {
        Start-Process powershell.exe -Verb RunAs -Wait `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded"
    } catch {
        Write-Host "UAC was declined or failed: $_" -ForegroundColor Red
        Send-Report 'uac-failed' @{ error = "$_" }
    }
    Write-Host ''
    Write-Host 'Stage 1 finished. The elevated window shows how stage 2 went.' -ForegroundColor Green
} catch {
    Write-Host "Stage 1 failed: $_" -ForegroundColor Red
    Send-Report 'error' @{ stage = 1; error = "$_"; where = $_.ScriptStackTrace }
}
Read-Host 'Press Enter to close'
