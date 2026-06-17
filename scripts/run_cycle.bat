@echo off
chcp 65001 >nul
cd /d D:\treasure
D:\treasure\venv\Scripts\python.exe -m github_radar.main >> data\cron.log 2>&1
