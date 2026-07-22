[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command,
        [Parameter(Mandatory)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

Push-Location $RepositoryRoot
try {
    & (Join-Path $PSScriptRoot "verify-fast.ps1")
    Invoke-CheckedCommand {
        uv run --system-certs --extra test pytest
    } "Python test suite"
    Invoke-CheckedCommand {
        pnpm install --frozen-lockfile
    } "Frontend dependency installation"
    Invoke-CheckedCommand { pnpm run check } "Playwright discovery"
    Invoke-CheckedCommand { pnpm run test:e2e } "Playwright test suite"
    Write-Output "Full verification passed."
}
finally {
    Pop-Location
}
