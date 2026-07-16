param(
    [string]$Address = "127.0.0.1",
    [int]$Port = 8000,
    [int]$Workers = 1,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if ($Address -notin @("127.0.0.1", "::1", "localhost")) {
    throw "FastAPI must bind to loopback behind the approved HTTPS gateway."
}
if ($Workers -ne 1) {
    throw "The approved initial process model is exactly one worker. Re-budget PostgreSQL before changing it."
}
if (-not $env:APP_DATABASE_URL) {
    $env:APP_DATABASE_URL = [Environment]::GetEnvironmentVariable("APP_DATABASE_URL", "User")
}
if (-not $env:APP_ORIGIN) {
    $env:APP_ORIGIN = [Environment]::GetEnvironmentVariable("APP_ORIGIN", "User")
}
if (-not $env:APP_COOKIE_SECURE) {
    $env:APP_COOKIE_SECURE = [Environment]::GetEnvironmentVariable("APP_COOKIE_SECURE", "User")
}

python -c "import fastapi, psycopg2, uvicorn; print('Runtime dependencies OK')"
if ($LASTEXITCODE -ne 0) { throw "Python runtime dependency check failed." }

python scripts\issue13_host_check.py --skip-origin-probe --workers $Workers --pool-max 5
if ($LASTEXITCODE -ne 0) { throw "Production host preflight failed." }

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "Port $Port is already in use." }
if ($CheckOnly) {
    Write-Host "React/FastAPI preflight passed; port $Port is free." -ForegroundColor Green
    exit 0
}

Write-Host "Starting one loopback-only FastAPI worker for the HTTPS gateway." -ForegroundColor Green
python -m uvicorn api.main:create_app --factory --host $Address --port $Port --workers $Workers --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --log-config config\uvicorn-logging.json
if ($LASTEXITCODE -ne 0) { throw "FastAPI exited with code $LASTEXITCODE." }
