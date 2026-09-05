[CmdletBinding()]
param(
    [string]$CertificatePath = (Join-Path $env:USERPROFILE 'Downloads\ca.pem')
)

$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot 'market-service\.venv\Scripts\python.exe'
$checker = Join-Path $PSScriptRoot 'scripts\check_cloud_mysql.py'
$privateDirectory = Join-Path $PSScriptRoot 'backups\cloud-mysql'
$previousUri = [Environment]::GetEnvironmentVariable('FINTRACK_CLOUD_MYSQL_URI', 'Process')
$secureUri = $null
$plainUri = $null

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'The FinTrack Python environment is missing. Run the local setup first.'
    }
    if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) {
        throw 'Download the Aiven CA certificate to Downloads\ca.pem first.'
    }
    New-Item -ItemType Directory -Path $privateDirectory -Force | Out-Null
    $certificateCopy = Join-Path $privateDirectory 'ca.pem'
    if (Test-Path -LiteralPath $certificateCopy) {
        $existingHash = (Get-FileHash -LiteralPath $certificateCopy -Algorithm SHA256).Hash
        $downloadHash = (Get-FileHash -LiteralPath $CertificatePath -Algorithm SHA256).Hash
        if ($existingHash -ne $downloadHash) {
            $certificateCopy = Join-Path $privateDirectory ('ca-' + $downloadHash.Substring(0, 16) + '.pem')
        }
    }
    if (-not (Test-Path -LiteralPath $certificateCopy)) {
        Copy-Item -LiteralPath $CertificatePath -Destination $certificateCopy
    }

    Write-Host 'This checks the cloud MySQL connection. It does not copy or change database data.'
    Write-Host 'Copy the complete Service URI from Aiven, then paste it at the prompt below.'
    Write-Host 'The pasted value is hidden. Do not send the URI in chat.'
    $secureUri = Read-Host 'Aiven MySQL Service URI' -AsSecureString
    $credential = New-Object System.Management.Automation.PSCredential('Aiven Service URI', $secureUri)
    $plainUri = $credential.GetNetworkCredential().Password
    [Environment]::SetEnvironmentVariable('FINTRACK_CLOUD_MYSQL_URI', $plainUri, 'Process')
    $reportPath = Join-Path $privateDirectory 'connection-check.json'
    & $pythonPath $checker --ca-file $certificateCopy --report-file $reportPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Connection check failed. No new credentials were saved; share only the error message.'
    }

    # Windows encrypts PSCredential exports for this Windows user and computer.
    # The directory is ignored by Git. No local MYSQL_* or DATABASE_URL settings change.
    $credential | Export-Clixml -LiteralPath (Join-Path $privateDirectory 'credential.xml')
    [pscustomobject]@{CertificatePath = $certificateCopy; ReportPath = $reportPath} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $privateDirectory 'settings.json') -Encoding UTF8
    Write-Host 'SUCCESS: Cloud MySQL connected with verified TLS.' -ForegroundColor Green
    Write-Host 'Connection details were saved encrypted for this Windows account.'
    Write-Host 'No data was migrated and the live website connection has not changed.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    [Environment]::SetEnvironmentVariable('FINTRACK_CLOUD_MYSQL_URI', $previousUri, 'Process')
    $plainUri = $null
    $credential = $null
    if ($secureUri) { $secureUri.Dispose() }
}
