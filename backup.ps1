param(
    [string]$DbName = "english_class",
    [string]$PgUser = "postgres",
    [string]$PgPort = "5432",
    [string]$BackupDir = "$PSScriptRoot\backups",
    [string]$SecondaryDir = "C:\Backups\english_class",
    [int]$RetentionDays = 30,
    [string]$PgPassword
)

$ErrorActionPreference = "Stop"

# Resolve pg_dump/pg_restore from PATH, else the newest local installation,
# so the script works unattended on any machine (matches the phase 8 gate).
function Resolve-PgTool([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\$Name.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Parent.Name) } -Descending
    if ($candidates) { return $candidates[0].FullName }
    throw "$Name was not found on PATH or under C:\Program Files\PostgreSQL"
}

$pgDump = Resolve-PgTool "pg_dump"
$pgRestore = Resolve-PgTool "pg_restore"

# Password precedence: parameter, current env, persisted user env, prompt.
# The persisted user env keeps scheduled runs non-interactive.
if (-not $PgPassword) { $PgPassword = $env:PGPASSWORD }
if (-not $PgPassword) { $PgPassword = [Environment]::GetEnvironmentVariable("PGPASSWORD", "User") }
if (-not $PgPassword) {
    $securePwd = Read-Host "PostgreSQL password for '$PgUser'" -AsSecureString
    $PgPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd))
}
$env:PGPASSWORD = $PgPassword

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $BackupDir "$DbName`_$timestamp.dump"

& $pgDump -U $PgUser -h localhost -p $PgPort -d $DbName -Fc -f $backupPath
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE"
}

# Cheap validity check: a corrupt dump fails to list its contents.
& $pgRestore -l $backupPath | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "backup verification failed: pg_restore could not read $backupPath"
}

Write-Host "Backup created: $backupPath" -ForegroundColor Green

# Second copy outside the OneDrive-synced repo folder.
if ($SecondaryDir) {
    New-Item -ItemType Directory -Force -Path $SecondaryDir | Out-Null
    Copy-Item -Path $backupPath -Destination $SecondaryDir -Force
    Write-Host "Secondary copy: $(Join-Path $SecondaryDir (Split-Path $backupPath -Leaf))" -ForegroundColor Green
}

# Retention: prune old timestamped dumps for this database in both locations.
if ($RetentionDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    foreach ($dir in @($BackupDir, $SecondaryDir)) {
        if ($dir -and (Test-Path $dir)) {
            Get-ChildItem -Path $dir -Filter "$DbName`_*.dump" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -lt $cutoff } |
                ForEach-Object {
                    Remove-Item $_.FullName -Force
                    Write-Host "Pruned old backup: $($_.FullName)" -ForegroundColor Yellow
                }
        }
    }
}

Write-Host "Restore test command: pg_restore -l `"$backupPath`"" -ForegroundColor Cyan
