# Install Go and Publish the Line-Ending Fix
## Status
ACTIVE
## Goal
Install the repository-pinned Go toolchain, document and audit it as required, then publish the verified line-ending and approval-rule changes through a pull request.
## Confirmed Context
- `config/quality-tools.env` pins `GO_VERSION=1.26.5` and the quality script requires `go` for actionlint and Gitleaks.
- WinGet identifies official package `GoLang.Go` version 1.26.5 from `https://go.dev`.
- The user explicitly authorized installation, commit, push, and pull-request creation.
## In Scope
- Local Go installation, existing local-tool rules/documentation, focused tests, current line-ending changes, commit, push, and a draft PR.
## Out of Scope
- Merge, deployment, production data, secrets, migrations, and remote repository settings.
## Constraints
- Use the official WinGet package, expose no secrets, stage only the confirmed task files, and do not merge without a later explicit approval.
## Execution Plan
1. Install and verify Go 1.26.5.
2. Add Go to the existing required-tool audit and local development documentation.
3. Run focused, quality, fast, and full verification as supported.
4. Inspect and stage only task files, commit, push, and create a draft PR.
## Validation Commands
- `go version`
- `pwsh -File scripts/check_local_tools.ps1`
- `just quality`
- `just fast`
- `just full`
- `python scripts/check_agents_length.py`
- `git diff --check`
## Definition of Done
- Go 1.26.5 is callable and the local audit treats it as required.
- Quality checks no longer fail because Go is missing.
- Intended changes are committed, pushed, and represented by a draft PR with no merge or deployment.
## Results
Pending.
