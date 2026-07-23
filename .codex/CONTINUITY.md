# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE
- Outcome: Refresh and complete the archive/current-publication row-adaptation
  extraction in existing PR #97.
- Task: `tasks/active/TASK.md`.

## Current Branch

- `codex/extract-archive-row-adaptation`
- Authoritative base: `origin/main` at
  `88fef120648adff8023aff3696ce2df042463ede`.
- Pre-refresh head: `06356f03b2d7106d501d377054ae0cceb8c78821`.
- Non-destructive merge head: `04f4879757826495f1a632a98f5d5c1657825ac6`.

## Completed Work

- Merged current `origin/main` into the existing feature branch without
  conflicts or production-code drift.
- Reinspected the extraction, callers, compatibility imports, contracts,
  counters, provenance, point-in-time gates, and writer lifecycle.
- Added direct regression coverage for within-source duplicates, incremental
  `previous=` accumulation, cross-source duplicates, publication precedence,
  provenance association, and writer success/abort ordering.
- Passed Focused, Ruff, basedpyright, diff, Fast, and final Full verification.

## Remaining Work

- Commit and push the refreshed evidence.
- Observe current-head PR #97 checks, repair only directly related failures,
  archive the task, restore the active task to `NONE`, and confirm merge
  readiness.
- Stop before updating `main` and request final protected-branch authorization.

## Key Decisions

- Reuse PR #97 and its original extraction; do not duplicate or rewrite it.
- Keep the builder responsible for verified reads, feature calculation, audit,
  persistence, exceptions, and writer orchestration.
- Preserve duplicate-date fail-closed behavior and provenance/counter semantics
  rather than introducing a behavior change during structural extraction.

## Validation Already Passed

- Focused venue feature suite: 21 passed.
- Pinned Ruff: passed.
- Pinned basedpyright: 0 errors and 0 warnings.
- Active-task contract, instruction limits, `git diff --check`, and changed-diff
  Gitleaks: passed.
- Fast verification: passed.
- Final Full verification: 999 Python and 65 Playwright tests passed.

## Known Issues or Blockers

- The first Full run had one transient iPhone 13 WebKit bounding-box failure.
  The screenshot showed correct layout; the exact case passed alone and the
  unchanged final Full rerun passed all 65 Playwright tests.
- No current blocker.

## Commit and Pull Request References

- Original implementation head:
  `06356f03b2d7106d501d377054ae0cceb8c78821`.
- Refresh merge:
  `04f4879757826495f1a632a98f5d5c1657825ac6`.
- Existing PR #97: https://github.com/migao2006/tool/pull/97

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
