# Один раз: создать ярлык Zoloto GitHub.lnk в корне проекта (+ на рабочий стол).
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "..\launcher\create-shortcut.ps1"
& powershell -NoProfile -ExecutionPolicy Bypass -File $script
