<#
  setup.ps1 -- One-shot setup for the English Class Management PostgreSQL DB
  on a fresh Windows machine.

  Usage (from PowerShell, inside this package's folder):
      .\setup.ps1

  Optional parameters:
      .\setup.ps1 -DbName "english_class" -PgUser "postgres" -PgPort 5432

  What it does:
    1. Checks for PostgreSQL (psql) and Python; tells you how to install
       them via winget if missing (then asks you to re-run).
    2. Creates the target database if it doesn't already exist.
    3. Installs the required Python packages.
    4. Creates/loads a new database or backs up an existing one.
    5. Applies versioned migrations.
    6. Creates a restricted database user for the app.
    7. Runs verification queries.
#>

param(
    [string]$DbName = "english_class",
    [string]$PgUser = "postgres",
    [string]$PgPort = "5432",
    [string]$PgPassword,
    [string]$AppUser = "english_class_app",
    [string]$AppPassword
)

$ErrorActionPreference = "Stop"

$draftLock = Join-Path $PSScriptRoot "DRAFT_MIGRATIONS.lock"
if (Test-Path $draftLock) {
    throw "Database migrations are being redesigned. Read DATA_DICTIONARY.md and TARGET_ARCHITECTURE.md; do not run setup until DRAFT_MIGRATIONS.lock is removed."
}

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Write-Host "== 1. Checking prerequisites ==" -ForegroundColor Cyan

$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) {
    Write-Host "PostgreSQL (psql) not found on PATH." -ForegroundColor Yellow
    Write-Host "Looking for an existing PostgreSQL installation under C:\Program Files\PostgreSQL..."
    $possible = Get-ChildItem "C:\Program Files\PostgreSQL" -Filter psql.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($possible) {
        Write-Host "Found PostgreSQL at: $($possible.FullName)" -ForegroundColor Green
        $env:Path = "$($possible.DirectoryName);$env:Path"
        $psql = Get-Command psql -ErrorAction SilentlyContinue
    }
}

if (-not $psql) {
    Write-Host "Installing with: winget install -e --id PostgreSQL.PostgreSQL.16"
    try {
        winget install -e --id PostgreSQL.PostgreSQL.16
    } catch {
        Write-Host "winget failed to download PostgreSQL. Please install PostgreSQL manually from:" -ForegroundColor Red
        Write-Host "  https://www.postgresql.org/download/windows/"
        Write-Host "Then reopen PowerShell, cd to this folder, and run .\setup.ps1 again." -ForegroundColor Yellow
        exit 1
    }
    Start-Sleep -Seconds 2
    $psql = Get-Command psql -ErrorAction SilentlyContinue
    if (-not $psql) {
        Write-Host "PostgreSQL was installed but psql still not found on PATH." -ForegroundColor Yellow
        Write-Host "If you installed via the PostgreSQL website, open a NEW PowerShell window and run .\setup.ps1 again." -ForegroundColor Yellow
        Write-Host "If psql is still missing, add its bin folder to PATH or run this script with the full psql path." -ForegroundColor Yellow
        Write-Host "Typical location: C:\Program Files\PostgreSQL\16\bin\psql.exe" -ForegroundColor Yellow
        exit 1
    }
    Write-Host ""
    Write-Host "Install finished. Close this PowerShell window, open a NEW one" -ForegroundColor Yellow
    Write-Host "(so PATH refreshes), cd back into this folder, and run .\setup.ps1 again."
    exit 0
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found on PATH." -ForegroundColor Yellow
    Write-Host "Installing with: winget install -e --id Python.Python.3.12"
    try {
        winget install -e --id Python.Python.3.12
    } catch {
        Write-Host "winget failed to download Python. Please install Python manually from:" -ForegroundColor Red
        Write-Host "  https://www.python.org/downloads/windows/"
        Write-Host "Then reopen PowerShell, cd to this folder, and run .\setup.ps1 again." -ForegroundColor Yellow
        exit 1
    }
    Write-Host ""
    Write-Host "Install finished. Close this PowerShell window, open a NEW one," -ForegroundColor Yellow
    Write-Host "cd back into this folder, and run .\setup.ps1 again."
    exit 0
}

Write-Host "psql and python found." -ForegroundColor Green

if (-not $PgPassword) {
    $securePwd = Read-Host "Enter the password for the 'postgres' PostgreSQL user" -AsSecureString
    $PgPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd))
}
$env:PGPASSWORD = $PgPassword

if (-not $AppPassword) {
    $secureAppPwd = Read-Host "Choose a password for the '$AppUser' application user" -AsSecureString
    $AppPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureAppPwd))
}

Write-Host "== 2. Creating database '$DbName' (if needed) ==" -ForegroundColor Cyan
$dbExists = & psql -U $PgUser -h localhost -p $PgPort -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'" 2>$null
Assert-NativeSuccess "Database lookup"
if ($dbExists -ne "1") {
    & psql -U $PgUser -h localhost -p $PgPort -c "CREATE DATABASE $DbName"
    Assert-NativeSuccess "Database creation"
    Write-Host "Database '$DbName' created." -ForegroundColor Green
    $isNewDatabase = $true
} else {
    Write-Host "Database '$DbName' already exists -- skipping create." -ForegroundColor Yellow
    $isNewDatabase = $false
}

Write-Host "== 3. Installing Python dependencies ==" -ForegroundColor Cyan
python -m pip install --quiet -r requirements.txt
Assert-NativeSuccess "Python dependency installation"

$encodedPgPassword = [System.Uri]::EscapeDataString($PgPassword)
$connStr = "postgresql://$PgUser`:$encodedPgPassword@localhost`:$PgPort/$DbName"

if ($isNewDatabase) {
    Write-Host "== 4. Creating schema and loading initial data ==" -ForegroundColor Cyan
    & psql -v ON_ERROR_STOP=1 -U $PgUser -h localhost -p $PgPort -d $DbName -f schema.sql
    Assert-NativeSuccess "Base schema"
    & psql -v ON_ERROR_STOP=1 -U $PgUser -h localhost -p $PgPort -d $DbName -f views.sql
    Assert-NativeSuccess "Reporting views"
    & psql -v ON_ERROR_STOP=1 -U $PgUser -h localhost -p $PgPort -d $DbName -f admin_schema.sql
    Assert-NativeSuccess "Admin schema"
    python etl.py okok_FIXED_v2.xlsx $connStr
    Assert-NativeSuccess "Initial data load"
} else {
    Write-Host "== 4. Preserving existing schema and data ==" -ForegroundColor Cyan
    Write-Host "Creating a pre-migration backup..." -ForegroundColor Cyan
    & "$PSScriptRoot\backup.ps1" -DbName $DbName -PgUser $PgUser -PgPort $PgPort -PgPassword $PgPassword
    & psql -v ON_ERROR_STOP=1 -U $PgUser -h localhost -p $PgPort -d $DbName -f admin_schema.sql
    Assert-NativeSuccess "Admin schema"
}

Write-Host "== 5. Applying versioned migrations ==" -ForegroundColor Cyan
python migrate.py $connStr
Assert-NativeSuccess "Database migrations"

Write-Host "== 6. Creating restricted application database user ==" -ForegroundColor Cyan
& psql -v ON_ERROR_STOP=1 -v app_user=$AppUser -v app_password=$AppPassword -U $PgUser -h localhost -p $PgPort -d $DbName -f database_roles.sql
Assert-NativeSuccess "Application database role"

$streamlitDir = Join-Path $PSScriptRoot ".streamlit"
New-Item -ItemType Directory -Force -Path $streamlitDir | Out-Null
$encodedAppPassword = [System.Uri]::EscapeDataString($AppPassword)
$appConnStr = "postgresql://$AppUser`:$encodedAppPassword@localhost`:$PgPort/$DbName"
$escapedAppConnStr = $appConnStr.Replace('"', '\"')
Set-Content -Path (Join-Path $streamlitDir "secrets.toml") -Value "[database]`nurl = `"$escapedAppConnStr`""

Write-Host "== 7. Verifying ==" -ForegroundColor Cyan
& psql -U $PgUser -h localhost -p $PgPort -d $DbName -c "SELECT * FROM v_dashboard_overview;"
Assert-NativeSuccess "Dashboard verification"
& psql -U $PgUser -h localhost -p $PgPort -d $DbName -c "SELECT issue_type, count(*) FROM data_quality_issues WHERE status='open' GROUP BY issue_type ORDER BY issue_type;"
Assert-NativeSuccess "Data quality verification"

Write-Host ""
Write-Host "Done. Expected: 308 total_students / 102 active / 195 inactive / 11 waiting_for_class." -ForegroundColor Green
Write-Host "The app connection is stored in .streamlit\secrets.toml (excluded from git)." -ForegroundColor Green
Write-Host "Run: python -m streamlit run app.py" -ForegroundColor Cyan
