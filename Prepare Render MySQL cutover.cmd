@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-render-mysql-cutover.ps1"
pause
