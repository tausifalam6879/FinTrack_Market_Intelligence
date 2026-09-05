[CmdletBinding()]
param([string]$AdminUser = 'root')

$ErrorActionPreference = 'Stop'

$mysqlService = Get-Service -Name 'MySQL80' -ErrorAction SilentlyContinue
if ($mysqlService -and $mysqlService.Status -ne 'Running') {
    Start-Service -Name $mysqlService.Name
    $mysqlService.WaitForStatus('Running', [TimeSpan]::FromSeconds(20))
}

$mysqlExecutable = Get-Command mysql.exe -ErrorAction SilentlyContinue
if (-not $mysqlExecutable) {
    $knownPath = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
    if (Test-Path -LiteralPath $knownPath) {
        $mysqlExecutable = Get-Item -LiteralPath $knownPath
    }
}
if (-not $mysqlExecutable) {
    throw 'MySQL client was not found. Install MySQL Server 8 and retry the FinTrack installer.'
}
$mysqlPath = if ($mysqlExecutable.Source) { $mysqlExecutable.Source } else { $mysqlExecutable.FullName }

$adminPassword = Read-Host "Enter the password for MySQL administrator '$AdminUser'" -AsSecureString
$adminCredential = New-Object System.Management.Automation.PSCredential($AdminUser, $adminPassword)
$plainAdminPassword = $adminCredential.GetNetworkCredential().Password

$randomBytes = New-Object byte[] 24
$randomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $randomGenerator.GetBytes($randomBytes)
} finally {
    $randomGenerator.Dispose()
}
$projectPassword = -join ($randomBytes | ForEach-Object { $_.ToString('x2') })

$sql = @"
CREATE DATABASE IF NOT EXISTS fintrack CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fintrack_mlflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'fintrack'@'localhost' IDENTIFIED BY '$projectPassword';
CREATE USER IF NOT EXISTS 'fintrack'@'127.0.0.1' IDENTIFIED BY '$projectPassword';
ALTER USER 'fintrack'@'localhost' IDENTIFIED BY '$projectPassword';
ALTER USER 'fintrack'@'127.0.0.1' IDENTIFIED BY '$projectPassword';
GRANT ALL PRIVILEGES ON fintrack.* TO 'fintrack'@'localhost';
GRANT ALL PRIVILEGES ON fintrack_mlflow.* TO 'fintrack'@'localhost';
GRANT ALL PRIVILEGES ON fintrack.* TO 'fintrack'@'127.0.0.1';
GRANT ALL PRIVILEGES ON fintrack_mlflow.* TO 'fintrack'@'127.0.0.1';
FLUSH PRIVILEGES;
"@

try {
    $env:MYSQL_PWD = $plainAdminPassword
    $sql | & $mysqlPath `
        --protocol=TCP --host=127.0.0.1 --port=3306 `
        --user=$AdminUser --batch --skip-column-names
    if ($LASTEXITCODE -ne 0) {
        throw 'MySQL rejected the administrator login or database setup command.'
    }
} finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    $plainAdminPassword = $null
}

$settings = @{
    MYSQL_HOST = '127.0.0.1'
    MYSQL_PORT = '3306'
    MYSQL_DATABASE = 'fintrack'
    MYSQL_USER = 'fintrack'
    MYSQL_PASSWORD = $projectPassword
}
foreach ($entry in $settings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'User')
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
}

Write-Host 'FinTrack MySQL databases and the dedicated application account are configured.'
Write-Host 'The generated application password was saved for this Windows account and was not printed.'
