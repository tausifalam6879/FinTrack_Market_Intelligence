@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0migrate-production-to-cloud-mysql.ps1"
pause
