param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$localUrl = 'http://127.0.0.1:5173/#top'
$logRoot = Join-Path $projectRoot '.runtime-logs'
$launcher = Join-Path $projectRoot 'start-local.ps1'
$mutex = $null
$hasLaunchLock = $false

function Test-FinTrackFrontend {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $localUrl -TimeoutSec 3
        return $response.StatusCode -eq 200 -and $response.Content -match 'FinTrack Market Intelligence'
    } catch {
        return $false
    }
}

function Test-FinTrackReadyEndpoint([string]$Uri) {
    try {
        $response = Invoke-RestMethod -Uri $Uri -TimeoutSec 3
        return $response.status -in @('ok', 'ready')
    } catch {
        return $false
    }
}

function Test-FinTrackOfflineModel {
    try {
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
        $installedModels = @($response.models | ForEach-Object { $_.name })
        return @('llama3.2:latest', 'llama3.2:1b') | Where-Object { $_ -in $installedModels } | Select-Object -First 1
    } catch {
        return $false
    }
}

function Test-FinTrackStack {
    return (
        (Test-FinTrackFrontend) -and
        (Test-FinTrackReadyEndpoint 'http://127.0.0.1:8002/health/ready') -and
        (Test-FinTrackReadyEndpoint 'http://127.0.0.1:8081/health/ready') -and
        (Test-FinTrackOfflineModel)
    )
}

function Open-FinTrackApp {
    $browserCandidates = @(
        (Get-Command msedge.exe -ErrorAction SilentlyContinue).Source,
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe'),
        (Get-Command chrome.exe -ErrorAction SilentlyContinue).Source,
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path $_) } | Select-Object -Unique

    $appBrowser = $browserCandidates | Select-Object -First 1
    if ($appBrowser) {
        # App mode keeps localhost and internal service ports out of the user interface.
        Start-Process -FilePath $appBrowser -ArgumentList "--app=$localUrl", '--start-maximized'
        return
    }

    # Fall back to the default browser when Edge or Chrome is unavailable.
    Start-Process $localUrl
}

try {
    if (-not (Test-FinTrackStack)) {
        $mutex = New-Object System.Threading.Mutex($false, 'Local\FinTrackMarketIntelligenceLauncher')
        $hasLaunchLock = $mutex.WaitOne(0)
        if ($hasLaunchLock -and -not (Test-FinTrackStack)) {
            New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
            $standardLog = Join-Path $logRoot 'fintrack.out.log'
            $errorLog = Join-Path $logRoot 'fintrack.error.log'
            Start-Process powershell.exe -WindowStyle Hidden `
                -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -ProductionFrontend -RequireOfflineAi" `
                -RedirectStandardOutput $standardLog -RedirectStandardError $errorLog
        }

        for ($attempt = 1; $attempt -le 60 -and -not (Test-FinTrackStack); $attempt++) {
            Start-Sleep -Seconds 2
        }
    }
} finally {
    if ($hasLaunchLock -and $mutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}

if (-not (Test-FinTrackStack)) {
    $errorLog = Join-Path $logRoot 'fintrack.error.log'
    $detail = if (Test-Path $errorLog) { (Get-Content $errorLog -Tail 8) -join [Environment]::NewLine } else { 'No launcher log was created.' }
    $failureMessage = "FinTrack could not start. Review .runtime-logs\fintrack.error.log.`n`n$detail"
    if (-not $NoBrowser) {
        try {
            Add-Type -AssemblyName PresentationFramework
            [System.Windows.MessageBox]::Show($failureMessage, 'FinTrack startup problem', 'OK', 'Error') | Out-Null
        } catch {
            # The full detail remains available in the runtime log when a GUI is unavailable.
        }
    }
    throw $failureMessage
}

if (-not $NoBrowser) {
    Open-FinTrackApp
}
