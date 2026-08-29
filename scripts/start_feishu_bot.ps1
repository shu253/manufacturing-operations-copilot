$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $projectRoot ".runtime"
$environmentFile = Join-Path $projectRoot ".env"
$processFile = Join-Path $runtimeDirectory "feishu-bot-process.json"
$standardOutput = Join-Path $runtimeDirectory "feishu-bot.stdout.log"
$standardError = Join-Path $runtimeDirectory "feishu-bot.stderr.log"

if (Test-Path -LiteralPath $environmentFile) {
    Get-Content -LiteralPath $environmentFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $name, $value = $line.Split("=", 2)
            [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
        }
    }
}

if (-not $env:FEISHU_APP_ID -or -not $env:FEISHU_APP_SECRET) {
    throw "Fill FEISHU_APP_ID and FEISHU_APP_SECRET in .env before starting the bot."
}

if (Test-Path -LiteralPath $processFile) {
    $existing = Get-Content -LiteralPath $processFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $running = Get-Process -Id ([int]$existing.pid) -ErrorAction SilentlyContinue
    if ($null -ne $running) {
        throw "The Feishu bot is already running with PID $($existing.pid)."
    }
    Remove-Item -LiteralPath $processFile -Force
}

if (-not (Test-Path -LiteralPath $runtimeDirectory)) {
    New-Item -ItemType Directory -Path $runtimeDirectory | Out-Null
}

$pythonExecutable = (Get-Command python -ErrorAction Stop).Source
# Some Windows launchers inject both PATH and Path. Start-Process treats them
# as duplicate dictionary keys, so normalize the process environment first.
$processPathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
Remove-Item Env:PATH -ErrorAction SilentlyContinue
$env:Path = $processPathValue
$botProcess = Start-Process -FilePath $pythonExecutable `
    -ArgumentList "-B", "-m", "channels.feishu_bot" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $standardOutput `
    -RedirectStandardError $standardError `
    -PassThru

@{
    pid = $botProcess.Id
    started_at = (Get-Date).ToString("o")
    stdout = $standardOutput
    stderr = $standardError
} | ConvertTo-Json | Set-Content -LiteralPath $processFile -Encoding UTF8

Start-Sleep -Seconds 2
$running = Get-Process -Id $botProcess.Id -ErrorAction SilentlyContinue
if ($null -eq $running) {
    Write-Output "The Feishu bot stopped during startup."
    if (Test-Path -LiteralPath $standardError) {
        Get-Content -LiteralPath $standardError -Tail 30
    }
    exit 1
}

Write-Output "Feishu bot started with PID $($botProcess.Id)."
Write-Output "Output log: $standardOutput"
Write-Output "Error log: $standardError"
Write-Output "Stop: powershell -ExecutionPolicy Bypass -File scripts\stop_feishu_bot.ps1"
