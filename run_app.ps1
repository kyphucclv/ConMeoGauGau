param(
    [string]$Address = "127.0.0.1",
    [int]$Port = 8501,
    [switch]$InstallDeps,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $PSScriptRoot
} else {
    $env:PYTHONPATH = "$PSScriptRoot;$env:PYTHONPATH"
}

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Test-LocalPort([string]$HostName, [int]$PortNumber) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $PortNumber, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(1000, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

Write-Host "== English Class Admin launcher ==" -ForegroundColor Cyan

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python was not found on PATH. Install Python, reopen PowerShell, then run run_app.cmd again."
}

Write-Host "Checking Python packages..." -ForegroundColor Cyan
if ($InstallDeps) {
    python -m pip install -r requirements.txt
    Assert-LastExitCode "Dependency installation"
}

python -c "import psycopg2, streamlit, tomllib; print('Python deps OK')"
Assert-LastExitCode "Python dependency check"

python -m streamlit version
Assert-LastExitCode "Streamlit check"

$secretsPath = Join-Path $PSScriptRoot ".streamlit\secrets.toml"
if (-not (Test-Path -LiteralPath $secretsPath) -and [string]::IsNullOrWhiteSpace($env:APP_DATABASE_URL) -and [string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
    throw "Database URL is missing. Create .streamlit\secrets.toml from .streamlit\secrets.example.toml, or set APP_DATABASE_URL."
}

Write-Host "Checking database connection and canonical schema..." -ForegroundColor Cyan
$healthScript = @'
import os
import tomllib
from pathlib import Path

from db import create_pool, fetch_one, verify_canonical_schema

database_url = os.getenv("APP_DATABASE_URL")
secrets_path = Path(".streamlit/secrets.toml")
if not database_url and secrets_path.exists():
    secrets = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    database_url = secrets.get("database", {}).get("url")
database_url = database_url or os.getenv("DATABASE_URL")
if not database_url:
    raise SystemExit("Database URL is not configured")

pool = create_pool(database_url)
try:
    verify_canonical_schema(pool)
    row = fetch_one(pool, "SELECT current_user AS db_user, current_database() AS db_name")
    print(f"Database OK: {row['db_user']}@{row['db_name']}")
finally:
    pool.closeall()
'@
$healthPath = Join-Path $env:TEMP "english_class_app_health.py"
Set-Content -LiteralPath $healthPath -Value $healthScript -Encoding UTF8
try {
    python $healthPath
    $healthExitCode = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $healthPath -ErrorAction SilentlyContinue
}
if ($healthExitCode -ne 0) {
    throw "Database health check failed with exit code $healthExitCode"
}

if (Test-LocalPort $Address $Port) {
    Write-Host "App already appears to be running at http://$Address`:$Port" -ForegroundColor Green
    if ($CheckOnly) {
        exit 0
    }
    Write-Host "Open that URL in your browser, or stop the existing process before starting another one." -ForegroundColor Yellow
    exit 0
}

if ($CheckOnly) {
    Write-Host "Checks passed. Port $Port is free." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "Starting Streamlit. Keep this window open while using the app." -ForegroundColor Green
Write-Host "URL: http://$Address`:$Port" -ForegroundColor Green
Write-Host "Press Ctrl+C in this window to stop the app." -ForegroundColor Yellow
Write-Host ""

python -m streamlit run streamlit_app.py --server.address=$Address --server.port=$Port --server.headless=true
Assert-LastExitCode "Streamlit app"
