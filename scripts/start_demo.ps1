$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$databasePath = Join-Path $projectRoot "data\huadong_jinggong_demo.sqlite3"
$webRoot = Join-Path $projectRoot "web"

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $databasePath)) {
        Write-Host "Generating deterministic demo data..."
        python .\scripts\generate_demo_data.py
    }

    if (-not (Test-Path -LiteralPath (Join-Path $webRoot "node_modules"))) {
        Write-Host "Installing web dependencies..."
        Push-Location $webRoot
        try { pnpm install --frozen-lockfile } finally { Pop-Location }
    }

    Write-Host "Building web application..."
    Push-Location $webRoot
    try { pnpm run build } finally { Pop-Location }

    $api = Start-Process -FilePath "python" `
        -ArgumentList "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $projectRoot -PassThru

    $web = Start-Process -FilePath "pnpm" `
        -ArgumentList "run", "preview", "--", "--host", "127.0.0.1", "--port", "5173" `
        -WorkingDirectory $webRoot -PassThru

    $runtime = Join-Path $projectRoot ".runtime"
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    @{
        api_pid = $api.Id
        web_pid = $web.Id
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime "demo-processes.json") -Encoding UTF8

    Write-Host "Web:      http://127.0.0.1:5173"
    Write-Host "API docs: http://127.0.0.1:8000/docs"
} finally {
    Pop-Location
}
