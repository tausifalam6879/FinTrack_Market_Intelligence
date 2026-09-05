[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$privateDirectory = Join-Path $PSScriptRoot 'backups\cloud-mysql'
$credentialPath = Join-Path $privateDirectory 'credential.xml'
$settingsPath = Join-Path $privateDirectory 'settings.json'
$targetUri = $null
$renderUri = $null

try {
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) {
        throw 'Saved Aiven credentials are missing. Run configure-cloud-mysql.ps1 first.'
    }
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw 'Saved Aiven settings are missing.'
    }
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $certificatePath = [string]$settings.CertificatePath
    if (-not (Test-Path -LiteralPath $certificatePath -PathType Leaf)) {
        throw 'The saved Aiven CA certificate is missing.'
    }
    $credential = Import-Clixml -LiteralPath $credentialPath
    $targetUri = $credential.GetNetworkCredential().Password
    $queryStart = $targetUri.IndexOf('?')
    $targetBase = if ($queryStart -ge 0) { $targetUri.Substring(0, $queryStart) } else { $targetUri }
    $renderUri = "${targetBase}?ssl-mode=VERIFY_IDENTITY&ssl-ca=%2Fetc%2Fsecrets%2Fca.pem"

    Get-Content -LiteralPath $certificatePath -Raw | Set-Clipboard
    Write-Host 'STEP 1: The Aiven CA certificate is copied to the clipboard.' -ForegroundColor Cyan
    Write-Host 'In Render > fintrack-market-intelligence-api > Environment > Secret Files:'
    Write-Host 'Add a secret file named ca.pem and paste its Contents. Do not save yet.'
    Read-Host 'After the CA contents are pasted in Render, press Enter here'

    Set-Clipboard -Value $renderUri
    Write-Host 'STEP 2: The complete Render MySQL DATABASE_URL is copied to the clipboard.' -ForegroundColor Cyan
    Write-Host 'Replace only the DATABASE_URL value in the same Render Environment page.'
    Write-Host 'Now choose Save, rebuild, and deploy so both changes apply together.'
    Write-Host 'Do not paste the value into chat.'
    Read-Host 'After saving DATABASE_URL in Render, press Enter here'
    # Windows PowerShell 5 treats an empty string as a null clipboard value.
    Set-Clipboard -Value ' '
    Write-Host 'Cutover settings submitted. The clipboard has been cleared.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    $targetUri = $null
    $renderUri = $null
    $credential = $null
}
