param([int]$Port = 8002)

$ErrorActionPreference = 'Stop'
$serviceRoot = Join-Path $PSScriptRoot 'market-service'
$venvPython = Join-Path $serviceRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = (& py -3.12 -c 'import sys; print(sys.executable)' | Select-Object -First 1)
} else {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
}
if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
    throw 'Python 3.12 is required to start the local research API.'
}

# Local-only defaults. Explicit provider choices and credentials are preserved.
$defaults = @{
    LLM_PROVIDER = 'hybrid'
    GEMINI_TIMEOUT_MS = '60000'
    OLLAMA_MODEL = 'llama3.2:latest'
    OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
    OLLAMA_TIMEOUT_MS = '45000'
    OLLAMA_KEEP_ALIVE = '30m'
    OLLAMA_NUM_CTX = '2048'
    OLLAMA_NUM_PREDICT = '80'
}
foreach ($entry in $defaults.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($entry.Key, 'Process'))) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
}
# A desktop app may have started before a user-level key was configured.
# Read only the named setting; never print credentials or persist them to files.
if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {
    $configuredKey = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')
    if (-not [string]::IsNullOrWhiteSpace($configuredKey)) { $env:GEMINI_API_KEY = $configuredKey }
}
if ($env:LLM_PROVIDER -in @('hybrid', 'auto', 'gemini') -and [string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {
    Write-Warning 'Local Gemini key is missing. Hybrid mode will try Ollama. Render settings do not configure this computer.'
}
Write-Host "Local research API: $Port | provider: $env:LLM_PROVIDER | Ollama model: $env:OLLAMA_MODEL"
Push-Location $serviceRoot
try {
    & $pythonExe -m uvicorn app:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
