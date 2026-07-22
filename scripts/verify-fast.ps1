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
    Invoke-CheckedCommand { python scripts/check_agents_length.py } "Agent instruction check"
    Invoke-CheckedCommand {
        uv run --system-certs --extra test pytest -q tests/test_agents_length.py
    } "Focused repository instruction tests"
    Invoke-CheckedCommand { git diff --check } "Git whitespace check"
    Write-Output "Fast verification passed."
}
finally {
    Pop-Location
}
