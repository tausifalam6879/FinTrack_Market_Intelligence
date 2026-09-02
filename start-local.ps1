param([switch]$InstallDependencies)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceRoot = Join-Path $projectRoot "market-service"
$gatewayRoot = Join-Path $projectRoot "gateway-service"
$frontendRoot = Join-Path $projectRoot "frontend"

function Test-FinTrackEndpoint([string]$Uri, [int]$TimeoutSeconds = 3) {
    try {
        $response = Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSeconds
        return $response.status -in @('ok', 'ready')
    } catch {
        return $false
    }
}

function Wait-FinTrackEndpoint([string]$Name, [string]$Uri, [int]$Attempts = 24) {
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        if (Test-FinTrackEndpoint $Uri) {
            Write-Host "${Name}: ready"
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become ready at $Uri. Check its local process logs and retry."
}

$basePython = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $basePython = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
}
if (-not $basePython -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $basePython = (Get-Command python).Source
}
if (-not $basePython -or -not (Test-Path $basePython)) {
    throw "Python 3.12 is not available. The project could not resolve an installed interpreter."
}

$ollamaReady = $false
try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    $ollamaReady = $true
    $warmBody = @{ model = "llama3.2:latest"; prompt = ""; stream = $false; keep_alive = "30m" } | ConvertTo-Json -Compress
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -ContentType 'application/json' -Body '$warmBody' -TimeoutSec 90 | Out-Null"
} catch {
    Write-Warning "Ollama is installed but its local service is not reachable. Start Ollama before asking offline questions."
}

$venvPython = Join-Path $serviceRoot ".venv\Scripts\python.exe"
if ($InstallDependencies) {
    if (-not (Test-Path $venvPython)) { & $basePython -m venv (Join-Path $serviceRoot ".venv") }
    & $venvPython -m pip install -r (Join-Path $serviceRoot "requirements.txt")
}
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { $basePython }
& $pythonExe -c "import fastapi, uvicorn, pandas, sklearn" 2>$null
if ($LASTEXITCODE -ne 0) { throw "Python dependencies are missing. Connect once and run: .\start-local.ps1 -InstallDependencies" }
if (-not (Test-Path (Join-Path $frontendRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Connect once, run npm install inside frontend, then retry."
}
$gatewayJar = Get-ChildItem (Join-Path $gatewayRoot "target\*.jar") -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gatewayJar) {
    throw "Spring gateway JAR is missing. Connect once and run .\mvnw.cmd package inside gateway-service."
}

if (-not (Test-FinTrackEndpoint 'http://127.0.0.1:8002/health/ready')) {
    $apiScript = Join-Path $projectRoot 'start-local-api.ps1'
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$apiScript`" -Port 8002"
}
Wait-FinTrackEndpoint 'FastAPI ML/data service' 'http://127.0.0.1:8002/health/ready'

if (-not (Test-FinTrackEndpoint 'http://127.0.0.1:8081/health/ready')) {
    Start-Process java.exe -WindowStyle Hidden -ArgumentList "-jar `"$($gatewayJar.FullName)`""
}
Wait-FinTrackEndpoint 'Spring gateway' 'http://127.0.0.1:8081/health/ready'

Write-Host "FinTrack Market Intelligence is ready."
Write-Host "Frontend: http://localhost:5173"
Write-Host "Spring gateway: http://localhost:8081/health/ready"
Write-Host "FastAPI ML/data service: http://localhost:8002/docs"
Write-Host "AI policy: Gemini on every question -> Ollama only after an actual failure/unusable answer -> verified fallback"
if ($ollamaReady) { Write-Host "Ollama: ready" }

Set-Location $frontendRoot
$env:VITE_MARKET_API_BASE_URL = 'http://localhost:8081'
npm run dev:frontend
