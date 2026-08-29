$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = (Get-Command python -ErrorAction Stop).Source

& $pythonExecutable -B -m channels.feishu_bot --check
exit $LASTEXITCODE

