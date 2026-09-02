[CmdletBinding(SupportsShouldProcess = $true)]
param([switch]$SkipLaunch)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeLauncher = Join-Path $projectRoot 'start-fintrack-background.ps1'
$preparationLauncher = Join-Path $projectRoot 'start-local.ps1'
$powerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$startupShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'FinTrack Market Intelligence.lnk'
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'FinTrack Market Intelligence.lnk'

if (-not $WhatIfPreference) {
    & $preparationLauncher -InstallDependencies -PrepareOnly -ProductionFrontend -RequireOfflineAi
    if ($LASTEXITCODE -ne 0) { throw 'FinTrack prerequisite preparation failed.' }
}

function New-FinTrackShortcut([string]$Path, [switch]$BackgroundOnly) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $powerShellExe
    $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runtimeLauncher`""
    if ($BackgroundOnly) { $arguments += ' -NoBrowser' }
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'Start FinTrack Market Intelligence with its local offline services'
    $shortcut.Save()
}

if ($PSCmdlet.ShouldProcess($desktopShortcut, 'Create FinTrack shortcut')) {
    New-FinTrackShortcut -Path $desktopShortcut
}
if ($PSCmdlet.ShouldProcess($startupShortcut, 'Create FinTrack sign-in shortcut')) {
    New-FinTrackShortcut -Path $startupShortcut -BackgroundOnly
}

if ($WhatIfPreference) {
    Write-Host 'FinTrack installer dry-run completed; no dependencies or shortcuts were changed.'
} else {
    Write-Host 'FinTrack is installed for this Windows account.'
    Write-Host 'It will start quietly at sign-in, and the desktop shortcut opens the local app.'
}

if (-not $SkipLaunch -and -not $WhatIfPreference) {
    & $runtimeLauncher
}
