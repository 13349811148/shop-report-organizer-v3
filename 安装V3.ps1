[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$marketplacePath = Join-Path $repoRoot ".agents\plugins\marketplace.json"

if (-not (Test-Path -LiteralPath $marketplacePath -PathType Leaf)) {
    throw "V3 marketplace file was not found: $marketplacePath"
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "The codex command was not found. Install or open the Codex desktop app first."
}

$marketplaceOutput = & codex plugin marketplace add $repoRoot 2>&1
if ($LASTEXITCODE -ne 0 -and ($marketplaceOutput -join "`n") -notmatch "already|exists|configured") {
    throw ($marketplaceOutput -join "`n")
}

& codex plugin add "shop-report-organizer-v3@personal"
if ($LASTEXITCODE -ne 0) {
    throw "V3 plugin installation failed."
}

Write-Host "Shop Report Organizer V3 installation completed. V2 was not modified."
Write-Host "Start a new Codex task and invoke the V3 plugin."
