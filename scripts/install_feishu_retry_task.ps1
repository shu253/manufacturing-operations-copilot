$ErrorActionPreference = "Stop"
$TaskName = "ZhangYu-Feishu-Outbox-Retry"
$HiddenLauncher = Join-Path $PSScriptRoot "run_feishu_retry_hidden.vbs"
if (-not (Test-Path -LiteralPath $HiddenLauncher)) {
    throw "Hidden retry launcher not found: $HiddenLauncher"
}
$WScript = "$env:SystemRoot\System32\wscript.exe"
$Action = New-ScheduledTaskAction `
    -Execute $WScript `
    -Argument "`"$HiddenLauncher`""
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -MultipleInstances IgnoreNew `
    -Hidden
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Retry failed Feishu outbox messages every five minutes" `
    -Force | Out-Null
$Installed = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
Write-Host "Scheduled task installed: $($Installed.TaskName)"
