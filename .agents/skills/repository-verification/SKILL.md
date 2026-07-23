---
name: repository-verification
description: Verify Alpha Lens repository instructions, affected tests, Git changes, and regression gates after code, documentation, cleanup, or structure changes; do not use it to claim unexecuted checks passed.
---

# Repository Verification

Use `just tools`, `just agents`, `just fast`, and `just full` as the supported local command interface when `just` is available; the referenced scripts remain the source of truth.

1. Run `git status --short --branch` and `git diff --name-status`; separate pre-existing work from the current task.
2. Run `python scripts/check_agents_length.py` and require all reported instruction limits to pass.
3. Run focused checks for affected code. Use `uv run --system-certs --extra test pytest <tests>` for Python and the existing Playwright server/config for frontend work.
4. Run `pwsh -File scripts/verify-fast.ps1`.
5. Run `pwsh -File scripts/verify-full.ps1` for the Full-verification cases defined
   by root `AGENTS.md`, including executable governance changes and Pull Request
   readiness.
6. Run `git diff --check`; inspect status, stat, name-status, full diff, untracked files, accidental deletions, generated output, and possible secrets.

For migrations, validate local/isolated reset, lint, compatibility, and rollback before any staged or production operation. Never expose secret values.

Report exact commands, exit codes, failures, skipped checks, and environmental
blockers. Never substitute a narrower check for a required check without saying so.
Do not rerun a successful Full suite after record-only edits that cannot affect its
coverage; rerun the smallest instruction or state checks instead.
