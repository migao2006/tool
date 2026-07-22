# Publish Codex workflow and local toolchain
## Status
ACTIVE
## Goal
Commit and push the verified Agent workflow architecture and local development toolchain from a clean branch based on the latest `origin/main`.
## Confirmed Context
- The original working tree is mixed, ahead by two patch-equivalent commits and behind `origin/main` by 72 commits.
- A clean isolated worktree was created at `origin/main` on `agent/publish-local-toolchain`.
- The user explicitly authorized push, but did not request a pull request, merge, or deployment.
## In Scope
- Agent workflow documentation and Skills.
- Local tool audit, just command interface, act configuration, and verification scripts.
- CI path detection required for those repository files.
- Commit and push the isolated branch.
## Out of Scope
- Product behavior, production deployment, data imports, migrations, remote settings, pull requests, and merging.
## Constraints
- Preserve the original dirty worktree unchanged.
- Do not force push or expose secrets.
- Push only after fast and full verification pass.
## Execution Plan
1. Overlay the exact verified workflow/toolchain files on latest `origin/main`.
2. Inspect scope and run Agent, fast, full, Git, and secret checks.
3. Commit and push `agent/publish-local-toolchain`.
4. Archive this task, reset active state, commit the record, and push again.
## Validation Commands
- `python scripts/check_agents_length.py`
- `pwsh -File scripts/verify-fast.ps1`
- `pwsh -File scripts/verify-full.ps1`
- `git diff --check`
- `git status --short`
- `git diff --stat`
- `git diff --name-status`
## Definition of Done
- The intended files are committed on a clean branch based on latest `origin/main`.
- Required verification passes and no secret or unrelated change is staged.
- The branch is pushed without force, PR, merge, deployment, or production operation.
## Results
Pending.
