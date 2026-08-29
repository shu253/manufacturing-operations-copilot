$projectRoot = Split-Path -Parent $PSScriptRoot
$processFile = Join-Path $projectRoot ".runtime\demo-processes.json"

if (-not (Test-Path -LiteralPath $processFile)) {
    Write-Output "No recorded demo processes were found."
    exit 0
}

$processInfo = Get-Content -LiteralPath $processFile -Raw -Encoding UTF8 | ConvertFrom-Json
$recordedProcessIds = @($processInfo.api_pid, $processInfo.web_pid)

foreach ($targetProcessId in $recordedProcessIds) {
    if ($null -ne $targetProcessId) {
        $process = Get-Process -Id ([int]$targetProcessId) -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            Stop-Process -InputObject $process -Force -ErrorAction SilentlyContinue
            Wait-Process -Id $process.Id -Timeout 5 -ErrorAction SilentlyContinue
        }
    }
}

Remove-Item -LiteralPath $processFile -Force
Write-Output "Demo services have been stopped."
