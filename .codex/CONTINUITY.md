# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE
- Outcome: Adopt `FULL_AUTONOMY_UNTIL_MAIN_UPDATE` as the repository authorization
  model with one final protected-branch update boundary.

## Current Branch

- `codex/update-main-authorization-policy`
- Based on `origin/main` at `7a7e431f4086eabbe458a4ad244c940ec8cac9ae`.

## Completed Work

- Verified a clean checkout and isolated a new feature branch.
- Identified the direct policy, task, Skill, continuity, and contract-test surfaces.
- Replaced the prior authorization boundary with one final protected-branch gate.
- Added regression coverage for automatic operations, safety, and handoff evidence.

## Remaining Work

- Complete final diff review, commits, push, and Pull Request readiness.
- Stop before updating `main` or another protected branch.

## Key Decisions

- Keep the layered instruction architecture and product contracts unchanged.
- Preserve completed reports as immutable historical evidence.
- Treat deployment, migration, production workflow, and release preparation as
  in-scope Work Package actions; only a protected-branch update needs final approval.

## Validation Already Passed

- Focused governance contracts: 11 passed.
- Ruff and basedpyright passed; instruction limits and changed-file Gitleaks passed.
- Fast verification passed.
- Full verification passed: 990 Python and 65 Playwright tests.

## Known Issues or Blockers

- None.

## Commit and Pull Request References

- No commit or PR yet for this Work Package.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
