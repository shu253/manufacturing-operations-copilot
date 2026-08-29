param(
    [string]$LocalUrl = "http://127.0.0.1:8000",
    [ValidateSet("auto", "http2", "quic")]
    [string]$Protocol = "http2"
)

$cloudflaredCommand = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cloudflaredCommand) {
    $cloudflaredPath = $cloudflaredCommand.Source
} else {
    $installedPath = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (Test-Path -LiteralPath $installedPath) {
        $cloudflaredPath = $installedPath
    } else {
        Write-Error "cloudflared was not found. Install cloudflared and run this script again."
        exit 1
    }
}

Write-Host "Creating a temporary HTTPS tunnel for $LocalUrl."
Write-Host "Cloudflare transport protocol: $Protocol"
Write-Host "Keep this window open and copy the generated trycloudflare.com URL."
Write-Host "Use that URL for PUBLIC_TOOL_BASE_URL and the Dify custom tool schema."
& $cloudflaredPath tunnel --protocol $Protocol --url $LocalUrl --no-autoupdate
