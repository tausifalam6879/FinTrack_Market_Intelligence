param(
    [switch]$InstallDependencies,
    [switch]$PrepareOnly,
    [switch]$ProductionFrontend,
    [switch]$RequireOfflineAi
)

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

function Test-FinTrackOllama {
    try {
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
        return $response
    } catch {
        return $null
    }
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

$requiredOllamaModel = 'llama3.2:1b'
$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
$ollamaTags = Test-FinTrackOllama
if (-not $ollamaTags -and $ollamaCommand) {
    Start-Process -FilePath $ollamaCommand.Source -ArgumentList 'serve' -WindowStyle Hidden
    for ($attempt = 1; $attempt -le 15 -and -not $ollamaTags; $attempt++) {
        Start-Sleep -Seconds 1
        $ollamaTags = Test-FinTrackOllama
    }
}

$ollamaReady = [bool]$ollamaTags
if ($ollamaReady) {
    $installedModels = @($ollamaTags.models | ForEach-Object { $_.name })
    if ($requiredOllamaModel -notin $installedModels -and $InstallDependencies) {
        if (-not $ollamaCommand) {
            throw "Ollama is running, but its command is not available in PATH, so $requiredOllamaModel cannot be downloaded automatically. Reinstall Ollama or add it to PATH, then retry."
        }
        & $ollamaCommand.Source pull $requiredOllamaModel
        if ($LASTEXITCODE -ne 0) { throw "Ollama model download failed: $requiredOllamaModel" }
        $ollamaTags = Test-FinTrackOllama
        $installedModels = @($ollamaTags.models | ForEach-Object { $_.name })
    }
    if ($requiredOllamaModel -notin $installedModels -and $RequireOfflineAi) {
        throw "Ollama model $requiredOllamaModel is missing. Connect once and run Install FinTrack for Windows.cmd."
    }
    $warmBody = @{
        model = $requiredOllamaModel
        prompt = 'ready'
        stream = $false
        keep_alive = '30m'
        options = @{ num_predict = 1 }
    } | ConvertTo-Json -Compress -Depth 4
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -ContentType 'application/json' -Body $warmBody -TimeoutSec 90 | Out-Null
    } catch {
        if ($RequireOfflineAi) {
            throw "Ollama model $requiredOllamaModel is installed but could not be loaded for offline use. Restart Ollama and retry."
        }
        Write-Warning "Ollama model $requiredOllamaModel could not be warmed up."
    }
} elseif ($RequireOfflineAi) {
    throw 'Ollama is required for offline questions but could not be started. Install Ollama once while online, then run the FinTrack installer again.'
} else {
    Write-Warning 'The local Ollama service is not reachable. Install or start Ollama before asking offline questions.'
}

$venvPython = Join-Path $serviceRoot ".venv\Scripts\python.exe"
if ($InstallDependencies) {
    if (-not (Test-Path $venvPython)) { & $basePython -m venv (Join-Path $serviceRoot ".venv") }
    & $venvPython -m pip install -r (Join-Path $serviceRoot "requirements-runtime.txt")
    if ($LASTEXITCODE -ne 0) { throw 'Python runtime dependency installation failed.' }
}
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { $basePython }
& $pythonExe -c "import fastapi, uvicorn, pandas, sklearn" 2>$null
if ($LASTEXITCODE -ne 0) { throw "Python dependencies are missing. Connect once and run: .\start-local.ps1 -InstallDependencies" }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'Node.js and npm are required for the local FinTrack interface.'
}
if ($InstallDependencies) {
    Push-Location $frontendRoot
    try {
        if (Test-Path (Join-Path $frontendRoot 'node_modules')) {
            # A running Vite process can hold native Rolldown files open on Windows.
            # Incremental install verifies the lockfile without deleting those files.
            npm install --prefer-offline --no-audit --no-fund
        } else {
            npm ci --no-audit --no-fund
        }
        $npmInstallExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($npmInstallExitCode -ne 0) { throw 'Frontend dependency installation failed.' }
}
if (-not (Test-Path (Join-Path $frontendRoot 'node_modules'))) {
    throw "Frontend dependencies are missing. Connect once, run npm install inside frontend, then retry."
}
$gatewayJar = Get-ChildItem (Join-Path $gatewayRoot "target\*.jar") -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike 'original-*' } |
    Select-Object -First 1
if ($InstallDependencies) {
    Push-Location $gatewayRoot
    try {
        .\mvnw.cmd --batch-mode package -DskipTests
        $gatewayBuildExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($gatewayBuildExitCode -ne 0) { throw 'Spring gateway build failed.' }
    $gatewayJar = Get-ChildItem (Join-Path $gatewayRoot 'target\*.jar') -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike 'original-*' } |
        Select-Object -First 1
}
if (-not $gatewayJar) {
    throw "Spring gateway JAR is missing. Connect once and run .\mvnw.cmd package inside gateway-service."
}
if (-not (Get-Command java.exe -ErrorAction SilentlyContinue)) {
    throw 'Java is required to start the local Spring gateway.'
}

$env:VITE_MARKET_API_BASE_URL = 'http://localhost:8081'
if ($ProductionFrontend -and ($InstallDependencies -or -not (Test-Path (Join-Path $frontendRoot 'dist\index.html')))) {
    Push-Location $frontendRoot
    try {
        npm run build
        $frontendBuildExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($frontendBuildExitCode -ne 0) { throw 'Local production frontend build failed.' }
}

if ($PrepareOnly) {
    Write-Host 'FinTrack offline prerequisites are ready.'
    return
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
if ($ProductionFrontend) {
    npm run preview -- --port 5173 --strictPort
} else {
    npm run dev:frontend
}
