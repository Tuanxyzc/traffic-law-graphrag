# ==============================================================================
# sync_data.ps1 — 1-Click Data Synchronization Runner for Windows (PowerShell)
# ==============================================================================
# Usage:
#   .\scripts\sync_data.ps1            # Run full synchronization
#   .\scripts\sync_data.ps1 -DryRun    # Dry-run validation only
#   .\scripts\sync_data.ps1 -Doc 168_2024_ND-CP # Sync specific document
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Doc,
    [switch]$SkipDocker,
    [switch]$SkipParser,
    [switch]$SkipRag
)

$ErrorActionPreference = "Stop"

$argsList = @("-m", "src.sync")

if ($DryRun) {
    $argsList += "--dry-run"
}
if ($Doc) {
    $argsList += @("--doc", $Doc)
}
if ($SkipDocker) {
    $argsList += "--skip-docker"
}
if ($SkipParser) {
    $argsList += "--skip-parser"
}
if ($SkipRag) {
    $argsList += "--skip-rag"
}

Write-Host "Running Traffic Law GraphRAG Data Synchronization..." -ForegroundColor Cyan
python @argsList
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[ERROR] Synchronization failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
