[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# A running terminal does not inherit PATH updates made by winget. Append the
# registered paths for this process only so a post-install audit is reliable.
$registeredPath = @(
    [Environment]::GetEnvironmentVariable("Path", "User")
    [Environment]::GetEnvironmentVariable("Path", "Machine")
) | Where-Object { $_ }
$env:Path = (@($env:Path) + $registeredPath) -join ";"

$tools = @(
    @{ Name = "git"; Command = "git"; Arguments = @("--version"); Required = $true }
    @{ Name = "gh"; Command = "gh"; Arguments = @("--version"); Required = $true }
    @{ Name = "codex"; Command = "codex"; Arguments = @("--version"); Required = $false }
    @{ Name = "uv"; Command = "uv"; Arguments = @("--version"); Required = $true }
    @{ Name = "python"; Command = "python"; Arguments = @("--version"); Required = $true }
    @{ Name = "pwsh"; Command = "pwsh"; Arguments = @("--version"); Required = $true }
    @{ Name = "node"; Command = "node"; Arguments = @("--version"); Required = $true }
    @{ Name = "pnpm"; Command = "pnpm"; Arguments = @("--version"); Required = $true }
    @{ Name = "go"; Command = "go"; Arguments = @("version"); Required = $true }
    @{ Name = "docker"; Command = "docker"; Arguments = @("--version"); Required = $false }
    @{ Name = "rg"; Command = "rg"; Arguments = @("--version"); Required = $true }
    @{ Name = "fd"; Command = "fd"; Arguments = @("--version"); Required = $false }
    @{ Name = "fzf"; Command = "fzf"; Arguments = @("--version"); Required = $false }
    @{ Name = "zoxide"; Command = "zoxide"; Arguments = @("--version"); Required = $false }
    @{ Name = "just"; Command = "just"; Arguments = @("--version"); Required = $true }
    @{ Name = "act"; Command = "act"; Arguments = @("--version"); Required = $false }
    @{ Name = "zizmor"; Command = "zizmor"; Arguments = @("--version"); Required = $true }
)

$results = foreach ($tool in $tools) {
    $requirement = if ($tool.Required) { "Required" } else { "Optional" }
    $command = Get-Command $tool.Command -ErrorAction SilentlyContinue
    if (-not $command) {
        [pscustomobject]@{
            Tool = $tool.Name
            Status = "MISSING"
            Version = "-"
            Requirement = $requirement
        }
        continue
    }

    try {
        $output = & $tool.Command @($tool.Arguments) 2>&1
        $exitCode = $LASTEXITCODE
        $version = ($output | Select-Object -First 1).ToString().Trim()
        $status = if ($exitCode -eq 0) { "OK" } else { "BROKEN" }
    }
    catch {
        $status = "BROKEN"
        $version = "Command failed"
    }

    [pscustomobject]@{
        Tool = $tool.Name
        Status = $status
        Version = $version
        Requirement = $requirement
    }
}

$results | Format-Table -AutoSize
$failedRequired = @(
    $results | Where-Object { $_.Requirement -eq "Required" -and $_.Status -ne "OK" }
)
if ($failedRequired.Count -gt 0) {
    Write-Error "Required local tools are missing or broken: $($failedRequired.Tool -join ', ')"
    exit 1
}

Write-Output "Required local tools are available. Optional missing or broken tools do not fail this audit."
