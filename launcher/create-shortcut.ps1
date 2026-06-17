# Creates Zoloto GitHub.lnk in project root — hidden launch (like Gitrend / Jarvis).
$ErrorActionPreference = "Stop"

$LauncherDir = $PSScriptRoot
$ProjectRoot = Split-Path $LauncherDir -Parent
$VbsPath = Join-Path $LauncherDir "Zoloto-GitHub.vbs"
$ShortcutPath = Join-Path $ProjectRoot "Zoloto GitHub.lnk"
$PythonIcon = Join-Path $ProjectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $VbsPath)) {
  Write-Error "Zoloto-GitHub.vbs not found in launcher folder."
  exit 1
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($ShortcutPath)
$link.TargetPath = $env:ComSpec
$link.Arguments = "/c wscript.exe //B //Nologo `"$VbsPath`""
$link.WorkingDirectory = $LauncherDir
$link.WindowStyle = 7
$link.Description = "Zoloto GitHub - Telegram admin bot"
if (Test-Path $PythonIcon) {
  $link.IconLocation = "$PythonIcon,0"
}
$link.Save()

Write-Host "OK: $ShortcutPath"

$cscript = Join-Path $env:SystemRoot "System32\cscript.exe"
$helper = Join-Path $LauncherDir "create-shortcut.vbs"
if (Test-Path $helper) {
  try {
    & $cscript //Nologo $helper *> $null
    Write-Host "Desktop shortcut: OK"
  } catch {
    Write-Host "Desktop: drag D:\treasure\Zoloto GitHub.lnk to your Desktop"
  }
}
