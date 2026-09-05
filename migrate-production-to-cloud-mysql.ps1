[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot 'market-service\.venv\Scripts\python.exe'
$migrationScript = Join-Path $PSScriptRoot 'scripts\migrate_cloud_mysql.py'
$privateDirectory = Join-Path $PSScriptRoot 'backups\cloud-mysql'
$credentialPath = Join-Path $privateDirectory 'credential.xml'
$settingsPath = Join-Path $privateDirectory 'settings.json'
$previousSource = [Environment]::GetEnvironmentVariable('FINTRACK_LEGACY_DATABASE_URI', 'Process')
$previousTarget = [Environment]::GetEnvironmentVariable('FINTRACK_CLOUD_MYSQL_URI', 'Process')
$secureSource = $null
$sourceUri = $null
$targetUri = $null

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'The FinTrack Python environment is missing.'
    }
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) {
        throw 'Run configure-cloud-mysql.ps1 successfully before migration.'
    }
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw 'Cloud MySQL settings are missing.'
    }
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $certificatePath = [string]$settings.CertificatePath
    if (-not (Test-Path -LiteralPath $certificatePath -PathType Leaf)) {
        throw 'The saved Aiven CA certificate is missing.'
    }
    $targetCredential = Import-Clixml -LiteralPath $credentialPath
    $targetUri = $targetCredential.GetNetworkCredential().Password

    Write-Host 'This copies the current live PostgreSQL/Neon data into the empty Aiven MySQL database.'
    Write-Host 'The old database and the live website remain unchanged during this step.'
    Write-Host 'Copy the complete current DATABASE_URL from Render, then paste it below.'
    Write-Host 'The pasted value is hidden. Do not send the URL in chat.'
    $secureSource = Read-Host 'Current Render DATABASE_URL (PostgreSQL/Neon)' -AsSecureString
    $sourceCredential = New-Object System.Management.Automation.PSCredential('Legacy database URL', $secureSource)
    $sourceUri = $sourceCredential.GetNetworkCredential().Password

    [Environment]::SetEnvironmentVariable('FINTRACK_LEGACY_DATABASE_URI', $sourceUri, 'Process')
    [Environment]::SetEnvironmentVariable('FINTRACK_CLOUD_MYSQL_URI', $targetUri, 'Process')
    $timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ')
    $manifestPath = Join-Path $privateDirectory ("migration-$timestamp.json")
    & $pythonPath $migrationScript --ca-file $certificatePath --manifest-file $manifestPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Migration check failed. No live website setting was changed.'
    }
    Write-Host 'SUCCESS: Production data copied to Aiven MySQL and verified.' -ForegroundColor Green
    Write-Host 'The old database is still unchanged and the website still uses it for now.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    [Environment]::SetEnvironmentVariable('FINTRACK_LEGACY_DATABASE_URI', $previousSource, 'Process')
    [Environment]::SetEnvironmentVariable('FINTRACK_CLOUD_MYSQL_URI', $previousTarget, 'Process')
    $sourceUri = $null
    $targetUri = $null
    $sourceCredential = $null
    $targetCredential = $null
    if ($secureSource) { $secureSource.Dispose() }
}
