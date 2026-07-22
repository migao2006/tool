# Local Development Tools (Windows)

This document defines the repository's supported local command-line workflow. It does not grant production access, supply secrets, or replace the underlying scripts.

## Command interface

The root `justfile` is a thin interface over repository scripts and reviewed local-only commands. Run `just --list` to discover recipes. `just fast`, `just full`, `just agents`, and `just tools` call the existing verification or audit scripts; the scripts remain the source of truth.

The only local GitHub Actions execution recipes are `actions-python`, `actions-frontend`, and `actions-security`. All are restricted to `.github/workflows/project-tests.yml`. Do not add data import, publication, migration, deployment, release, or remote-write workflows to this allowlist.

The recipes use the workflow's `workflow_dispatch` event locally. Its scope-selection job intentionally selects the complete requested test scope without requiring a synthetic pull-request payload or a remote `git fetch`.

## Supported tools

| Tool | Requirement | Trusted source | Verify | Purpose and Codex usage |
| --- | --- | --- | --- | --- |
| Git | Required | git-scm / winget | `git --version` | Inspect and record repository changes; no commit or push without authorization. |
| GitHub CLI | Required | GitHub / winget | `gh --version` | Read GitHub repository, checks, and configuration. Never print tokens or mutate settings without approval. |
| gh Agent Skill | Optional | `cli/cli`, user-scoped | `gh skill list` | Provides official GitHub CLI command guidance to Codex. Review Skills before use. |
| uv | Required | Astral / winget | `uv --version` | Manage locked Python environments and tools using Windows system certificates. |
| Python | Required | Python Software Foundation | `python --version` | Run repository scripts, tests, data checks, and model research. |
| PowerShell 7 | Required | Microsoft | `pwsh --version` | Run Windows verification and tool audit scripts. |
| Node.js and pnpm | Required | Official distributions | `node --version`; `pnpm --version` | Run frontend dependency and Playwright commands. |
| Go | Required | Go project / `GoLang.Go` on winget | `go version` | Run the pinned actionlint and Gitleaks quality checks. Match `GO_VERSION` in `config/quality-tools.env`. |
| Docker Desktop | Optional | Docker | `docker version`; `docker info` | Provides the container engine required by most `act` jobs; not required for ordinary script checks. |
| ripgrep | Required | BurntSushi / trusted distribution | `rg --version` | Primary repository text search. |
| fd | Optional | sharkdp / winget | `fd --version` | Fast filename search. |
| fzf | Optional | junegunn / winget | `fzf --version` | Interactive fuzzy search for a developer; do not invoke interactively in unattended checks. |
| zoxide | Optional | ajeetdsouza / winget | `zoxide --version` | Faster interactive directory navigation. |
| just | Required | Casey.Just / winget | `just --version` | Run the repository's thin command interface without duplicating scripts. |
| act | Optional | nektos.act / winget | `act --version`; `act -l` | List workflows and run only reviewed, local-safe jobs with Docker. |
| zizmor | Required | `zizmorcore/zizmor` / `uv tool` | `zizmor --version` | Read-only GitHub Actions security analysis; do not auto-fix findings without review. |
| gh-dash | Optional, third-party | `dlvhdr/gh-dash` | `gh dash --help` | Interactive GitHub dashboard for a developer; Codex should not open it unattended. |

Run `pwsh -File scripts/check_local_tools.ps1` or `just tools` for a non-destructive local audit. Missing optional tools are reported but do not fail the audit. The script does not install software or call remote services.

## Windows notes

- Use Windows system certificates. For uv, use `uv ... --system-certs`; never disable TLS validation.
- winget PATH changes apply to newly opened terminals. The audit script appends registered user and machine PATH entries only for its own process.
- Go is a required quality-gate dependency. Install only the reviewed `GoLang.Go` package and keep it aligned with `config/quality-tools.env`; do not replace the pinned actionlint or Gitleaks checks with unreviewed binaries.
- The current-user PowerShell profile may initialize zoxide with `Invoke-Expression (& { (zoxide init powershell | Out-String) })`. Preserve existing profile content and never add the line twice.
- Do not set `strict-ssl=false`, `NODE_TLS_REJECT_UNAUTHORIZED=0`, or `GIT_SSL_NO_VERIFY=true`.

## Safe local GitHub Actions testing

Always run `act -l` before selecting a job. Inspect its trigger, permissions, environment, secrets, deployment steps, migration steps, and remote writes. The reviewed allowlist is:

- `python-tests` in `.github/workflows/project-tests.yml`
- `frontend-tests` in `.github/workflows/project-tests.yml`
- `quality-security` in `.github/workflows/project-tests.yml`

All other jobs are blocked by default. In particular, never run jobs that import or publish market data, upload model results, deploy Edge Functions, migrate databases, or require production secrets. Do not copy GitHub Secrets into local files. `act` is not identical to GitHub-hosted runners: images, services, event payloads, permissions, caches, and hosted tools may differ.

The repository `.actrc` maps `ubuntu-24.04` to act's documented medium image, `catthehacker/ubuntu:act-latest`, so unattended listing and dry-runs do not trigger the first-run selector. This third-party image is maintained for act compatibility but is not an exact GitHub-hosted runner snapshot. Review image trust and update policy before executing a job.

## GitHub Actions security audit

Run `just zizmor` for the regular audit and `just zizmor-pedantic` for additional code-smell findings. A non-zero exit caused by findings means the audit did not pass; it is not a tool failure. Review action pinning, minimal permissions, template injection, checkout credential persistence, artifact handling, and secret exposure. Do not rewrite workflows merely to reduce the count, and document any repository-specific accepted risk.

## Installation policy

Confirm exact package identifiers with `winget search` and metadata with `winget show` before installation. Use `uv tool install --system-certs zizmor` for zizmor and `gh skill install cli/cli gh --agent codex --scope user` for the official gh Skill. Avoid unknown remote scripts, elevated installers, redundant linters or scanners, and unrelated agent platforms.
