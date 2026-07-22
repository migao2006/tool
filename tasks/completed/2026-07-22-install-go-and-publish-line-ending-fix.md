# Install Go and Publish the Line-Ending Fix
## Status
COMPLETED
## Goal
Install the repository-pinned Go toolchain, document and audit it as required, then publish the verified line-ending and approval-rule changes through a pull request.
## Confirmed Context
- `config/quality-tools.env` pins `GO_VERSION=1.26.5` and the quality script requires `go` for actionlint and Gitleaks.
- WinGet identified official package `GoLang.Go` version 1.26.5 from `https://go.dev`.
- The user explicitly authorized installation, commit, push, and pull-request creation.
## In Scope
- Local Go installation, existing local-tool rules/documentation, focused tests, current line-ending changes, commit, push, and a draft PR.
## Out of Scope
- Merge, deployment, production data, secrets, migrations, and remote repository settings.
## Constraints
- Use an official Go source, expose no secrets, stage only confirmed task files, and do not merge without later explicit approval.
## Execution Plan
1. Install and verify Go 1.26.5.
2. Add Go to the existing required-tool audit and local development documentation.
3. Run focused, quality, fast, and full verification.
4. Inspect and stage only task files, commit, push, and create a draft PR.
## Validation Commands
- `go version`
- `pwsh -File scripts/check_local_tools.ps1`
- `just quality`
- `just full`
- `python scripts/check_agents_length.py`
- `git diff --check`
## Definition of Done
- Go 1.26.5 is callable and the local audit treats it as required.
- Quality checks no longer fail because Go is missing.
- Intended changes are committed, pushed, and represented by a draft PR with no merge or deployment.
## Results
- The WinGet MSI was verified as official but stopped with installer code 1602 after waiting for elevation. The official `go1.26.5.windows-amd64.zip` was then installed user-scoped from `go.dev`; its SHA256 matched the official release manifest.
- `go version` reports `go1.26.5 windows/amd64`, and the local tool audit reports Go as a working required tool.
- Fixed Deno checkout attributes and Windows Python-to-Bash path newlines. Eight focused contract tests passed.
- `just quality` passed action pinning, migrations, locks, CSP, Ruff, basedpyright, pre-commit, Biome, Deno, actionlint, Gitleaks, pip-audit, and SQLFluff. Gitleaks found no leaks.
- `just full` passed 976 Python tests and 65 Playwright tests. Agent instructions remain within all size limits and `git diff --check` passed.
- Commit `dafc178` was pushed to `agent/publish-local-toolchain` and draft PR #96 was created: https://github.com/migao2006/tool/pull/96
- No merge, deployment, production data, secret, migration, or remote setting change was performed.
