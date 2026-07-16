param(
    [Parameter(Mandatory = $true)]
    [string]$Hostname,
    [Parameter(Mandatory = $true)]
    [string]$ServerAddress,
    [Parameter(Mandatory = $true)]
    [string]$DiagnosticPath
)

$ErrorActionPreference = "Stop"
trap {
    $message = $_.Exception.Message + [Environment]::NewLine + $_.InvocationInfo.PositionMessage
    [IO.File]::WriteAllText($DiagnosticPath, $message, [Text.Encoding]::UTF8)
    exit 1
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this verifier from an elevated PowerShell process."
}

Restart-Service -Name EnglishClassReact -Force
$deadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Milliseconds 500
    try { $appReady = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/health/ready" -TimeoutSec 2).StatusCode -eq 200 }
    catch { $appReady = $false }
} until ($appReady -or (Get-Date) -ge $deadline)
if (-not $appReady) { throw "FastAPI was not ready after restart." }

Restart-Service -Name EnglishClassCaddy -Force
$deadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Milliseconds 500
    try { $httpsReady = (Invoke-WebRequest -UseBasicParsing "https://$Hostname/api/health/ready" -TimeoutSec 2).StatusCode -eq 200 }
    catch { $httpsReady = $false }
} until ($httpsReady -or (Get-Date) -ge $deadline)
if (-not $httpsReady) { throw "HTTPS gateway was not ready after restart." }

$task = Get-ScheduledTask -TaskName "EnglishClassDbBackup" -ErrorAction Stop
$backupStarted = Get-Date
Start-ScheduledTask -TaskName "EnglishClassDbBackup"
$deadline = (Get-Date).AddMinutes(2)
do {
    Start-Sleep -Seconds 1
    $task = Get-ScheduledTask -TaskName "EnglishClassDbBackup"
} until ($task.State -ne "Running" -or (Get-Date) -ge $deadline)
if ($task.State -eq "Running") { throw "Backup task did not finish within two minutes." }
$taskInfo = Get-ScheduledTaskInfo -TaskName "EnglishClassDbBackup"
if ($taskInfo.LastTaskResult -ne 0) { throw "Backup task failed with result $($taskInfo.LastTaskResult)." }

$latestBackup = Get-ChildItem -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) "backups") `
    -Filter "english_class_*.dump" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latestBackup -or $latestBackup.LastWriteTime -lt $backupStarted.AddSeconds(-2) -or $latestBackup.Length -le 0) {
    throw "A new non-empty verified backup was not created."
}

$base = Join-Path $env:ProgramData "EnglishClass"
$rootCertificate = Get-ChildItem -LiteralPath (Join-Path $base "caddy-data") -Recurse -Filter root.crt -File |
    Select-Object -First 1
if (-not $rootCertificate) { throw "Caddy root certificate was not found." }
$certificate = New-Object Security.Cryptography.X509Certificates.X509Certificate2($rootCertificate.FullName)
$clientBundle = Join-Path $env:PUBLIC "Documents\EnglishClass"
New-Item -ItemType Directory -Force -Path $clientBundle | Out-Null
$clientRoot = Join-Path $clientBundle "english-class-root.crt"
Copy-Item -LiteralPath $rootCertificate.FullName -Destination $clientRoot -Force
$clientInstaller = @'
$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell process."
}
$certificatePath = Join-Path $PSScriptRoot "english-class-root.crt"
Import-Certificate -FilePath $certificatePath -CertStoreLocation "Cert:\LocalMachine\Root" | Out-Null
Write-Output "English Class internal CA installed."
'@
Set-Content -LiteralPath (Join-Path $clientBundle "install-root-ca.ps1") -Value $clientInstaller -Encoding UTF8
Set-Content -LiteralPath (Join-Path $clientBundle "dns-record.txt") `
    -Value "$Hostname -> $ServerAddress" -Encoding ASCII

$appLogFiles = Get-ChildItem -LiteralPath (Join-Path $base "logs\app") -File -ErrorAction SilentlyContinue
$appLogText = ($appLogFiles | Get-Content -Raw -ErrorAction SilentlyContinue) -join [Environment]::NewLine
$forbiddenLogPattern = "(?i)postgres(?:ql)?://|english_class_session\s*=|(?:password|csrf(?:_token)?|app_database_url)\s*[=:]\s*['`"]?[^\s'`"]+"
$accessEventCount = ([regex]::Matches($appLogText, '"event":"http_request"')).Count
$forbiddenLogContent = [regex]::IsMatch($appLogText, $forbiddenLogPattern)
if ($forbiddenLogContent) { throw "Application logs contain a forbidden secret-shaped value." }
$appServiceXml = [xml](Get-Content -Raw -LiteralPath (Join-Path $base "app-service\EnglishClassReact.xml"))
$caddyServiceXml = [xml](Get-Content -Raw -LiteralPath (Join-Path $base "caddy-service\EnglishClassCaddy.xml"))

$services = Get-Service -Name EnglishClassReact,EnglishClassCaddy | ForEach-Object {
    [ordered]@{name=$_.Name; status=$_.Status.ToString(); start_type=$_.StartType.ToString()}
}
$listeners = Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in @(80,443,8000,5432)} | ForEach-Object {
    [ordered]@{address=$_.LocalAddress; port=$_.LocalPort; process_id=$_.OwningProcess}
}
$firewall = Get-NetFirewallRule -DisplayName "English Class*" | ForEach-Object {
    $rule = $_
    $ports = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule
    $addresses = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule
    [ordered]@{
        name=$rule.DisplayName
        action=$rule.Action.ToString()
        enabled=$rule.Enabled.ToString()
        local_port=($ports.LocalPort -join ",")
        remote_address=($addresses.RemoteAddress -join ",")
    }
}
$evidence = [ordered]@{
    checked_at=(Get-Date).ToUniversalTime().ToString("o")
    services=$services
    listeners=$listeners
    firewall=$firewall
    backup_task=[ordered]@{
        state=$task.State.ToString()
        run_as=$task.Principal.UserId
        last_result=$taskInfo.LastTaskResult
        last_run=$taskInfo.LastRunTime.ToUniversalTime().ToString("o")
        backup_file=$latestBackup.Name
        backup_bytes=$latestBackup.Length
    }
    certificate=[ordered]@{
        subject=$certificate.Subject
        thumbprint=$certificate.Thumbprint
        not_after=$certificate.NotAfter.ToUniversalTime().ToString("o")
        client_bundle=$clientBundle
    }
    logging=[ordered]@{
        access_events=$accessEventCount
        forbidden_secret_pattern_found=$forbiddenLogContent
        app_keep_files=[int]$appServiceXml.service.log.keepFiles
        caddy_keep_files=[int]$caddyServiceXml.service.log.keepFiles
    }
    restart_https_ready=$httpsReady
}
[IO.File]::WriteAllText($DiagnosticPath, ($evidence | ConvertTo-Json -Depth 6), [Text.Encoding]::UTF8)
