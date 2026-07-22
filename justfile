set shell := ["pwsh", "-NoProfile", "-Command"]

# List the repository command interface.
default:
    just --list

# Show the current branch and working-tree state.
status:
    git status --short --branch

# Validate repository Agent instruction limits.
agents:
    python scripts/check_agents_length.py

# Run the practical local pre-commit verification.
fast:
    pwsh -NoProfile -File scripts/verify-fast.ps1

# Run the complete local regression suite.
full:
    pwsh -NoProfile -File scripts/verify-full.ps1

# Run the repository's pinned quality and security checks.
quality:
    & (Join-Path $env:ProgramFiles 'Git\bin\bash.exe') scripts/run_quality_security_checks.sh

# Check the local development toolchain without installing anything.
tools:
    pwsh -NoProfile -File scripts/check_local_tools.ps1

# Inspect whitespace and the current change summary.
diff:
    git diff --check
    git diff --stat
    git diff --name-status

# List local GitHub Actions jobs without executing them.
actions-list:
    act -l

# Run only the reviewed local-safe Python test job.
actions-python:
    act workflow_dispatch -W .github/workflows/project-tests.yml -j python-tests

# Run only the reviewed local-safe frontend test job.
actions-frontend:
    act workflow_dispatch -W .github/workflows/project-tests.yml -j frontend-tests

# Run only the reviewed local-safe quality and security job.
actions-security:
    act workflow_dispatch -W .github/workflows/project-tests.yml -j quality-security

# Audit GitHub Actions without automatic fixes.
zizmor:
    zizmor .github

# Include pedantic GitHub Actions findings without automatic fixes.
zizmor-pedantic:
    zizmor --pedantic .github
