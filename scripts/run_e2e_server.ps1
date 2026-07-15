$ErrorActionPreference = 'Stop'

if (-not $env:PGPASSWORD) {
    $env:PGPASSWORD = [Environment]::GetEnvironmentVariable('PGPASSWORD', 'User')
}
if (-not $env:PGPASSWORD) {
    throw 'PGPASSWORD is required for the disposable browser-test database.'
}

$env:APP_DATABASE_URL = 'postgresql://postgres@localhost:5432/english_class_pytest'
$env:APP_ORIGIN = 'http://127.0.0.1:8012'
$env:APP_COOKIE_SECURE = 'false'

Set-Location (Split-Path -Parent $PSScriptRoot)
python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8012
