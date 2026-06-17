# Zoloto GitHub admin bot — hidden launch.
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$LauncherDir = $PSScriptRoot
$ProjectRoot = (Resolve-Path (Join-Path $LauncherDir "..")).Path
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$LockFile = Join-Path $ProjectRoot "data\bot.launch.lock"

function Show-Error([string]$Message) {
  [System.Windows.Forms.MessageBox]::Show($Message, "Zoloto GitHub", "OK", "Error") | Out-Null
}

if (-not (Test-Path $Python)) {
  Show-Error "venv\Scripts\python.exe not found.`n`ncd D:\treasure`npython -m venv venv`n.\venv\Scripts\pip install -r requirements.txt"
  exit 1
}

$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match "github_radar\.bot" }
if ($running) {
  exit 0
}

if (Test-Path $LockFile) {
  Remove-Item $LockFile -Force
}

$dataDir = Join-Path $ProjectRoot "data"
if (-not (Test-Path $dataDir)) {
  New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
}

Set-Content -Path $LockFile -Value (Get-Date -Format "o") -Encoding utf8

Start-Process -FilePath $Python `
  -ArgumentList "-m", "github_radar.bot" `
  -WorkingDirectory $ProjectRoot `
  -WindowStyle Hidden
