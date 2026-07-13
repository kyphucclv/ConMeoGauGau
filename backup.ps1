param(
    [string]$DbName = "english_class",
    [string]$PgUser = "postgres",
    [string]$PgPort = "5432",
    [string]$BackupDir = "$PSScriptRoot\backups",
    [string]$PgPassword
)

$ErrorActionPreference = "Stop"

if (-not $PgPassword) {
    $securePwd = Read-Host "PostgreSQL password for '$PgUser'" -AsSecureString
    $PgPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd))
}
$env:PGPASSWORD = $PgPassword

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $BackupDir "$DbName`_$timestamp.dump"

& pg_dump -U $PgUser -h localhost -p $PgPort -d $DbName -Fc -f $backupPath
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE"
}

Write-Host "Backup created: $backupPath" -ForegroundColor Green
Write-Host "Restore test command: pg_restore -l `"$backupPath`"" -ForegroundColor Cyan

