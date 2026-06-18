# Zoloto GitHub — ярлык запускает бота. Не убивает уже работающего (двойной клик = гонка).
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$LauncherDir = $PSScriptRoot
$ProjectRoot = (Resolve-Path (Join-Path $LauncherDir "..")).Path
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$DataDir = Join-Path $ProjectRoot "data"
$LockFile = Join-Path $DataDir "bot.launch.lock"
$LaunchingFlag = Join-Path $DataDir "shortcut.launching"

function Show-Info([string]$Message) {
  [System.Windows.Forms.MessageBox]::Show($Message, "Zoloto GitHub", "OK", "Information") | Out-Null
}

function Show-Error([string]$Message) {
  [System.Windows.Forms.MessageBox]::Show($Message, "Zoloto GitHub", "OK", "Error") | Out-Null
}

function Get-RadarBots {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -match '^python(w)?\.exe$' -and
      $_.CommandLine -match 'github_radar\.bot'
    }
}

if (-not (Test-Path $Python)) {
  Show-Error "venv\Scripts\python.exe not found.`n`ncd D:\treasure`npython -m venv venv`n.\venv\Scripts\pip install -r requirements.txt"
  exit 1
}

if (-not (Test-Path $DataDir)) {
  New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

if (Test-Path $LaunchingFlag) {
  $age = (Get-Date) - (Get-Item $LaunchingFlag).LastWriteTime
  if ($age.TotalSeconds -lt 45) {
    Show-Info "Запуск уже идёт — подождите 10–15 сек и проверьте Telegram.`n`nТам появится прогресс-бар."
    exit 0
  }
  Remove-Item $LaunchingFlag -Force -ErrorAction SilentlyContinue
}

$bots = @(Get-RadarBots)
if ($bots.Count -eq 1) {
  $botPid = $bots[0].ProcessId
  Show-Info "Бот уже работает (PID $botPid).`n`nОткройте Telegram — /status или /run.`n`nПолная остановка: /stopall"
  exit 0
}

Set-Content -Path $LaunchingFlag -Value (Get-Date -Format "o") -Encoding utf8

try {
  if ($bots.Count -gt 1) {
    foreach ($proc in $bots) {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 800
  }

  foreach ($name in @('radar.lock', 'cycle.lock', 'bot.launch.lock', 'bot.instance.lock')) {
    $path = Join-Path $DataDir $name
    if (Test-Path $path) {
      Remove-Item $path -Force -ErrorAction SilentlyContinue
    }
  }

  Set-Content -Path $LockFile -Value (Get-Date -Format "o") -Encoding utf8

  $proc = Start-Process -FilePath $Python `
    -ArgumentList "-m", "github_radar.bot" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

  Start-Sleep -Seconds 4
  $alive = @(Get-RadarBots)
  if ($alive.Count -ge 1) {
    Show-Info "Бот запущен (PID $($alive[0].ProcessId)).`n`nСмотрите Telegram — через несколько секунд придёт прогресс-бар."
  } else {
    Show-Error "Бот не поднялся. Откройте data\radar.log — последние строки.`n`nИли напишите боту /start в личку."
  }
}
finally {
  if (Test-Path $LaunchingFlag) {
    Remove-Item $LaunchingFlag -Force -ErrorAction SilentlyContinue
  }
}
