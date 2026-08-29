$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$processFile = Join-Path $projectRoot ".runtime\feishu-bot-process.json"

if (-not (Test-Path -LiteralPath $processFile)) {
    Write-Output "No recorded Feishu bot process was found."
    exit 0
}

$processInfo = Get-Content -LiteralPath $processFile -Raw -Encoding UTF8 | ConvertFrom-Json
$process = Get-Process -Id ([int]$processInfo.pid) -ErrorAction SilentlyContinue
if ($null -ne $process) {
    Stop-Process -InputObject $process -Force
    Wait-Process -Id $process.Id -Timeout 5 -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath $processFile -Force
Write-Output "Feishu bot has been stopped."

