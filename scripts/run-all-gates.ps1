# Run the full verification battery in one command.
# Fast suite first (seconds), then the heavyweight disposable-DB gates.
# Usage (from repo root):  .\scripts\run-all-gates.ps1  [-SkipHeavy] [-TargetHost]

param(
    [switch]$SkipHeavy,
    [switch]$TargetHost
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
if (-not $env:PGPASSWORD) {
    $env:PGPASSWORD = [Environment]::GetEnvironmentVariable("PGPASSWORD", "User")
}
if (-not $env:MIGRATION_DATABASE_URL) {
    $env:MIGRATION_DATABASE_URL = [Environment]::GetEnvironmentVariable("MIGRATION_DATABASE_URL", "User")
}

$results = [ordered]@{}

function Invoke-Gate([string]$Name, [scriptblock]$Command) {
    Write-Host "`n===== $Name =====" -ForegroundColor Cyan
    $started = Get-Date
    & $Command
    $ok = ($LASTEXITCODE -eq 0)
    $script:results[$Name] = @{ ok = $ok; seconds = [int]((Get-Date) - $started).TotalSeconds }
    if (-not $ok) { Write-Host "$Name FAILED (exit $LASTEXITCODE)" -ForegroundColor Red }
}

Invoke-Gate "pytest fast suite"        { python -m pytest tests/ -q }
Invoke-Gate "openapi contract check"   { npm --prefix web run api:check }
Invoke-Gate "react unit suite"         { npm --prefix web test }
Invoke-Gate "react production build"   { npm --prefix web run build }
Invoke-Gate "npm high severity audit"  { npm --prefix web audit --audit-level=high }
Invoke-Gate "phase13 dictionary check" { python scripts/phase13_dictionary_check.py }

if ($TargetHost) {
    if (-not $env:APP_DATABASE_URL) { $env:APP_DATABASE_URL = [Environment]::GetEnvironmentVariable("APP_DATABASE_URL", "User") }
    if (-not $env:APP_ORIGIN) { $env:APP_ORIGIN = [Environment]::GetEnvironmentVariable("APP_ORIGIN", "User") }
    if (-not $env:APP_COOKIE_SECURE) { $env:APP_COOKIE_SECURE = [Environment]::GetEnvironmentVariable("APP_COOKIE_SECURE", "User") }
    Invoke-Gate "target HTTPS host check" { python scripts/issue13_host_check.py }
}

if (-not $SkipHeavy) {
    Invoke-Gate "playwright read journey"  { npm --prefix web run test:e2e }
    Invoke-Gate "phase8 automated UAT"     { python scripts/phase8_automated_uat.py }
    Invoke-Gate "phase9 cutover rehearsal" { python scripts/phase9_cutover_rehearsal.py }
    Invoke-Gate "phase10 sign-off gate"    { python scripts/phase10_quality_signoff.py --validate-decisions }
    Invoke-Gate "phase11 decision gate"    { python scripts/phase11_operational_issue_snapshot.py --validate-decisions }
}

Write-Host "`n===== Summary =====" -ForegroundColor Cyan
$failed = 0
foreach ($entry in $results.GetEnumerator()) {
    $status = if ($entry.Value.ok) { "PASS" } else { $failed++; "FAIL" }
    $color = if ($entry.Value.ok) { "Green" } else { "Red" }
    Write-Host ("{0,-28} {1}  ({2}s)" -f $entry.Key, $status, $entry.Value.seconds) -ForegroundColor $color
}
if ($failed -gt 0) {
    Write-Host "`n$failed gate(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host "`nAll gates passed." -ForegroundColor Green
