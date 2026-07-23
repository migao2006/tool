# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: COMPLETE
- Outcome: Adopted `FULL_AUTONOMY_UNTIL_MAIN_UPDATE` with one final
  protected-branch update boundary.
- Record: `tasks/completed/2026-07-23-update-main-authorization-policy.md`.

## Current Branch

- `codex/update-main-authorization-policy`
- Based on `origin/main` at `7a7e431f4086eabbe458a4ad244c940ec8cac9ae`.

## Completed Work

- Replaced the prior authorization boundary with one final protected-branch gate.
- Added regression coverage for automatic operations, safety, and handoff evidence.
- Completed local Full verification and core GitHub Project tests.
- Pushed the feature branch and marked PR #99 Ready for review.

## Remaining Work

- Human review and final protected-branch authorization.
- Do not merge or otherwise update `main` without that authorization.

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

- Core commit: `3d0f398698b871af218663ad9c0ffbd0aa24e958`.
- Terminal task record follows the core commit.
- Ready PR #99: https://github.com/migao2006/tool/pull/99

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
