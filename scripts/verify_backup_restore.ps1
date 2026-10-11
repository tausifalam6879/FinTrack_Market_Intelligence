param(
    [Parameter(Mandatory=$true)][string]$CaFile,
    [Parameter(Mandatory=$true)][string]$BackupFile,
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
& docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw "Start Docker before backup/restore verification." }
& $Python "$PSScriptRoot/backup_cloud_mysql.py" --ca-file $CaFile --backup-file $BackupFile
if ($LASTEXITCODE -ne 0) { throw "Backup failed." }
& $Python "$PSScriptRoot/rehearse_mysql_restore.py" $BackupFile
if ($LASTEXITCODE -ne 0) { throw "Restore rehearsal failed." }
