[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$shortcutPaths = @(
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'FinTrack Market Intelligence.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'FinTrack Market Intelligence.lnk')
)

foreach ($shortcutPath in $shortcutPaths) {
    if (Test-Path -LiteralPath $shortcutPath) {
        if ($PSCmdlet.ShouldProcess($shortcutPath, 'Remove FinTrack shortcut')) {
            Remove-Item -LiteralPath $shortcutPath -Force
        }
    }
}

if ($WhatIfPreference) {
    Write-Host 'FinTrack uninstaller dry-run completed; no shortcuts were changed.'
} else {
    Write-Host 'FinTrack Windows shortcuts were removed. Project data and application files were kept.'
}
