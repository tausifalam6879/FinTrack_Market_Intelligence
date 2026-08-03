$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceRoot = Join-Path $projectRoot "market-service"
$frontendRoot = Join-Path $projectRoot "frontend"

Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "Set-Location '$serviceRoot'; if (-not (Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\python.exe -m pip install -r requirements.txt; .\.venv\Scripts\python.exe -m uvicorn app:app --reload --port 8002"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "Set-Location '$frontendRoot'; if (-not (Test-Path node_modules)) { npm install }; npm run dev"

Write-Host "FinTrack Market Intelligence is starting."
Write-Host "Frontend: http://localhost:5173"
Write-Host "API docs: http://localhost:8002/docs"

