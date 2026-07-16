param(
    [Parameter(Mandatory = $true)]
    [string]$Hostname,
    [Parameter(Mandatory = $true)]
    [string]$ServerAddress,
    [Parameter(Mandatory = $true)]
    [string]$LanSubnet,
    [Parameter(Mandatory = $true)]
    [string]$CaddySource,
    [Parameter(Mandatory = $true)]
    [string]$WinSWSource,
    [string]$DiagnosticPath
)

$ErrorActionPreference = "Stop"
trap {
    if ($DiagnosticPath) {
        $message = $_.Exception.Message + [Environment]::NewLine + $_.InvocationInfo.PositionMessage
        [IO.File]::WriteAllText($DiagnosticPath, $message, [Text.Encoding]::UTF8)
    }
    exit 1
}
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this installer from an elevated PowerShell process."
}
if ($Hostname -notmatch '^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$') {
    throw "Hostname is invalid."
}
$parsedAddress = $null
if (-not [ipaddress]::TryParse($ServerAddress, [ref]$parsedAddress)) {
    throw "ServerAddress must be an IP address."
}
foreach ($source in @($CaddySource, $WinSWSource)) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Required binary is missing: $source" }
}

$repo = Split-Path $PSScriptRoot -Parent
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$pythonDirectory = Split-Path $pythonPath -Parent
$appDatabaseUrl = [Environment]::GetEnvironmentVariable("APP_DATABASE_URL", "User")
$pgPassword = [Environment]::GetEnvironmentVariable("PGPASSWORD", "User")
if (-not $appDatabaseUrl) { throw "User-scoped APP_DATABASE_URL is required." }
if (-not $pgPassword) { throw "User-scoped PGPASSWORD is required for the backup task." }

$base = Join-Path $env:ProgramData "EnglishClass"
$appService = Join-Path $base "app-service"
$caddyService = Join-Path $base "caddy-service"
$caddyData = Join-Path $base "caddy-data"
$logs = Join-Path $base "logs"
$appLogs = Join-Path $logs "app"
$caddyLogs = Join-Path $logs "caddy"
$backup = Join-Path $base "backup"
foreach ($path in @($base, $appService, $caddyService, $caddyData, $logs, $appLogs, $caddyLogs, $backup)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

Copy-Item -LiteralPath $WinSWSource -Destination (Join-Path $appService "EnglishClassReact.exe") -Force
Copy-Item -LiteralPath $WinSWSource -Destination (Join-Path $caddyService "EnglishClassCaddy.exe") -Force
Copy-Item -LiteralPath $CaddySource -Destination (Join-Path $caddyService "caddy.exe") -Force

$xmlDatabaseUrl = [Security.SecurityElement]::Escape($appDatabaseUrl)
$xmlRepo = [Security.SecurityElement]::Escape($repo)
$xmlAppLogs = [Security.SecurityElement]::Escape($appLogs)
$xmlCaddyLogs = [Security.SecurityElement]::Escape($caddyLogs)
$xmlCaddyData = [Security.SecurityElement]::Escape($caddyData)
$xmlPythonDirectory = [Security.SecurityElement]::Escape($pythonDirectory)
$postgresService = Get-Service | Where-Object {$_.Name -match '^postgresql.*17$'} | Select-Object -First 1
$postgresDependency = if ($postgresService) { "<depend>$([Security.SecurityElement]::Escape($postgresService.Name))</depend>" } else { "" }

$appXml = @"
<service>
  <id>EnglishClassReact</id>
  <name>English Class React/FastAPI</name>
  <description>Canonical English Class React/FastAPI application.</description>
  <executable>C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe</executable>
  <arguments>-NoProfile -NonInteractive -ExecutionPolicy Bypass -File &quot;$xmlRepo\run_react_app.ps1&quot;</arguments>
  <workingdirectory>$xmlRepo</workingdirectory>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  $postgresDependency
  <serviceaccount><username>LocalSystem</username></serviceaccount>
  <env name="APP_DATABASE_URL" value="$xmlDatabaseUrl" />
  <env name="APP_ORIGIN" value="https://$Hostname" />
  <env name="APP_COOKIE_SECURE" value="true" />
  <env name="PYTHONDONTWRITEBYTECODE" value="1" />
  <env name="PATH" value="$xmlPythonDirectory;$xmlPythonDirectory\Scripts;%PATH%" />
  <hidewindow>true</hidewindow>
  <onfailure action="restart" delay="5 sec" />
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>20 sec</stoptimeout>
  <logpath>$xmlAppLogs</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>14</keepFiles></log>
</service>
"@
Set-Content -LiteralPath (Join-Path $appService "EnglishClassReact.xml") -Value $appXml -Encoding UTF8

$caddyFile = @"
{
    servers {
        protocols h1 h2
    }
}

$Hostname {
    tls internal
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000 {
        health_uri /api/health/ready
        health_interval 30s
        health_timeout 5s
    }
}
"@
Set-Content -LiteralPath (Join-Path $caddyService "Caddyfile") -Value $caddyFile -Encoding UTF8
& (Join-Path $caddyService "caddy.exe") validate --config (Join-Path $caddyService "Caddyfile") --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw "Caddy configuration validation failed." }

$caddyXml = @"
<service>
  <id>EnglishClassCaddy</id>
  <name>English Class HTTPS Gateway</name>
  <description>Caddy HTTPS gateway for the canonical English Class application.</description>
  <executable>%BASE%\caddy.exe</executable>
  <arguments>run --config &quot;%BASE%\Caddyfile&quot; --adapter caddyfile</arguments>
  <workingdirectory>$([Security.SecurityElement]::Escape($caddyService))</workingdirectory>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <depend>EnglishClassReact</depend>
  <serviceaccount><username>NT AUTHORITY\LocalService</username></serviceaccount>
  <env name="XDG_DATA_HOME" value="$xmlCaddyData" />
  <env name="XDG_CONFIG_HOME" value="$xmlCaddyData" />
  <hidewindow>true</hidewindow>
  <onfailure action="restart" delay="5 sec" />
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>20 sec</stoptimeout>
  <logpath>$xmlCaddyLogs</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>14</keepFiles></log>
</service>
"@
Set-Content -LiteralPath (Join-Path $caddyService "EnglishClassCaddy.xml") -Value $caddyXml -Encoding UTF8

$escapedPassword = $pgPassword.Replace("'", "''")
$escapedRepo = $repo.Replace("'", "''")
$backupScript = @"
`$ErrorActionPreference = 'Stop'
`$env:PGPASSWORD = '$escapedPassword'
& '$escapedRepo\backup.ps1'
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
"@
$backupScriptPath = Join-Path $backup "run-backup.ps1"
Set-Content -LiteralPath $backupScriptPath -Value $backupScript -Encoding UTF8

# Protect service configuration and secrets. LocalService can read Caddy's
# executable/config and modify only its data and log directories.
& icacls.exe $base /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
& icacls.exe $base /grant '*S-1-5-19:RX' | Out-Null
& icacls.exe $caddyService /grant:r '*S-1-5-19:(OI)(CI)RX' | Out-Null
& icacls.exe $caddyData /grant:r '*S-1-5-19:(OI)(CI)M' | Out-Null
& icacls.exe $caddyLogs /grant:r '*S-1-5-19:(OI)(CI)M' | Out-Null

$hostsPath = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
$existingHost = Get-Content -LiteralPath $hostsPath | Where-Object {$_ -match "(^|\s)$([regex]::Escape($Hostname))(\s|$)"}
if ($existingHost -and $existingHost -notmatch "^\s*$([regex]::Escape($ServerAddress))\s+") {
    throw "Hosts file already maps $Hostname to another address."
}
if (-not $existingHost) {
    [IO.File]::AppendAllText($hostsPath, "`r`n$ServerAddress`t$Hostname`r`n", [Text.Encoding]::ASCII)
}

$firewallRules = @(
    @{Name="English Class HTTPS LAN"; Action="Allow"; Ports=@(443); Remote=$LanSubnet},
    @{Name="English Class HTTP Redirect LAN"; Action="Allow"; Ports=@(80); Remote=$LanSubnet},
    @{Name="English Class Block Backend Ports"; Action="Block"; Ports=@(8000,8501,5432); Remote="Any"}
)
foreach ($rule in $firewallRules) {
    Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action $rule.Action -Protocol TCP `
        -LocalPort $rule.Ports -RemoteAddress $rule.Remote -Profile Any | Out-Null
}

$appWrapper = Join-Path $appService "EnglishClassReact.exe"
$caddyWrapper = Join-Path $caddyService "EnglishClassCaddy.exe"
foreach ($service in @(
    @{Name="EnglishClassCaddy"; Wrapper=$caddyWrapper},
    @{Name="EnglishClassReact"; Wrapper=$appWrapper}
)) {
    if (Get-Service -Name $service.Name -ErrorAction SilentlyContinue) {
        Stop-Service -Name $service.Name -Force -ErrorAction SilentlyContinue
        & $service.Wrapper uninstall | Out-Null
    }
}
& $appWrapper install | Out-Null
& $caddyWrapper install | Out-Null

$taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$backupScriptPath`""
$taskTrigger = New-ScheduledTaskTrigger -Daily -At "12:00"
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "EnglishClassDbBackup" -Action $taskAction -Trigger $taskTrigger `
    -Principal $taskPrincipal -Settings $taskSettings -Description "Verified daily English Class PostgreSQL backup." -Force | Out-Null

Start-Service -Name EnglishClassReact
$deadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Milliseconds 500
    try { $ready = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/health/ready" -TimeoutSec 2).StatusCode -eq 200 }
    catch { $ready = $false }
} until ($ready -or (Get-Date) -ge $deadline)
if (-not $ready) { throw "FastAPI service did not become ready." }

Start-Service -Name EnglishClassCaddy
$rootDeadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Milliseconds 500
    $rootCertificate = Get-ChildItem -LiteralPath $caddyData -Recurse -Filter root.crt -File -ErrorAction SilentlyContinue | Select-Object -First 1
} until ($rootCertificate -or (Get-Date) -ge $rootDeadline)
if (-not $rootCertificate) { throw "Caddy internal CA root was not generated." }
Import-Certificate -FilePath $rootCertificate.FullName -CertStoreLocation "Cert:\LocalMachine\Root" | Out-Null

Write-Output "Issue 13 host installation completed."
Write-Output "Hostname: $Hostname"
Write-Output "Server address: $ServerAddress"
Write-Output "Caddy root certificate: $($rootCertificate.FullName)"
if ($DiagnosticPath) { [IO.File]::WriteAllText($DiagnosticPath, "success", [Text.Encoding]::UTF8) }
