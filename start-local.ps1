$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceRoot = Join-Path $projectRoot "market-service"
$gatewayRoot = Join-Path $projectRoot "gateway-service"
$frontendRoot = Join-Path $projectRoot "frontend"

$ollamaReady = $false
try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    $ollamaReady = $true
    $warmBody = @{ model = "llama3.2:latest"; prompt = ""; stream = $false; keep_alive = "30m" } | ConvertTo-Json -Compress
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -ContentType 'application/json' -Body '$warmBody' -TimeoutSec 90 | Out-Null"
} catch {
    Write-Warning "Ollama is installed but its local service is not reachable. Start Ollama before asking offline questions."
}

$apiCommand = "Set-Location '$serviceRoot'; `$env:LLM_PROVIDER='hybrid'; `$env:GEMINI_TIMEOUT_MS='8000'; `$env:GEMINI_CIRCUIT_COOLDOWN_SECONDS='10'; `$env:OLLAMA_MODEL='llama3.2:latest'; `$env:OLLAMA_BASE_URL='http://127.0.0.1:11434'; `$env:OLLAMA_TIMEOUT_MS='30000'; `$env:OLLAMA_KEEP_ALIVE='30m'; if (-not (Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\python.exe -m pip install -r requirements.txt; .\.venv\Scripts\python.exe -m uvicorn app:app --reload --port 8002"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", $apiCommand
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "Set-Location '$gatewayRoot'; .\mvnw.cmd spring-boot:run"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "Set-Location '$frontendRoot'; `$env:VITE_MARKET_API_BASE_URL='http://localhost:8081'; if (-not (Test-Path node_modules)) { npm install }; npm run dev"

Write-Host "FinTrack Market Intelligence is starting."
Write-Host "Frontend: http://localhost:5173"
Write-Host "Spring gateway: http://localhost:8081/health/ready"
Write-Host "FastAPI ML/data service: http://localhost:8002/docs"
Write-Host "AI policy: Gemini (8s maximum) -> Ollama llama3.2 -> verified deterministic fallback"
if ($ollamaReady) { Write-Host "Ollama: ready" }
