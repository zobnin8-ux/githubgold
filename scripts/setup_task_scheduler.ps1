# Registers Windows Task Scheduler: "Zoloto GitHub" — 3x/day (~9 posts)
# Run once in PowerShell:
#   powershell -ExecutionPolicy Bypass -File D:\treasure\scripts\setup_task_scheduler.ps1

$TaskName = "Zoloto GitHub"
$BatPath = "D:\treasure\scripts\run_cycle.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "Missing $BatPath"
    exit 1
}

# Delete old task if exists
schtasks /Delete /TN $TaskName /F 2>$null | Out-Null

# Daily at 09:00, repeat every 480 min (8 h) for 24 h → ~09:00, 17:00, 01:00
schtasks /Create `
    /TN $TaskName `
    /TR $BatPath `
    /SC DAILY `
    /ST 09:00 `
    /RI 480 `
    /DU 24:00 `
    /F | Out-Null

# Run missed task after PC wake
$task = Get-ScheduledTask -TaskName $TaskName
$settings = $task.Settings
$settings.StartWhenAvailable = $true
$settings.ExecutionTimeLimit = "PT2H"
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries = $false
Set-ScheduledTask -TaskName $TaskName -Settings $settings | Out-Null

Write-Host "OK: Task '$TaskName' registered."
Write-Host "Runs ~09:00, 17:00, 01:00 when PC is on (3 posts each = ~9/day)."
Write-Host "Log: D:\treasure\data\cron.log"
Write-Host ""
Write-Host "Check: taskschd.msc  or  schtasks /Query /TN `"$TaskName`" /V /FO LIST"
