# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: COMPLETE
- Outcome: one safe owner-triggered full daily update workflow is released on
  `main`.
- Active record: `tasks/active/TASK.md` is `NONE`.
- Implementation record:
  `tasks/completed/2026-07-24-add-safe-manual-full-update-workflow.md`.
- Release record:
  `tasks/completed/2026-07-24-record-manual-full-update-main-release.md`.
- Authorization: the user explicitly authorized merging PR #102 and updating
  protected `main`.

## Current Branch

- Branch: `main`.
- Implementation merge commit:
  `53d16233c1ffd494ccb18cc5b53ec550585f8689`.
- PR #102 merged by normal merge commit with exact head guard.

## Completed Work

- `Manual full update` is active at
  `.github/workflows/manual-full-update.yml` and remains dispatch-only.
- Defaults are `dry_run=false`, `publish_production=true`, and blank
  `as_of_date`; no calendar date is substituted for a validated snapshot.
- Existing Import and Daily concurrency, resolver, ranking, Staging,
  Production, validation, bounded recovery, and persistent Issue logic remain
  the sole implementation paths.
- Final summaries fail closed on missing or inconsistent source, resolution,
  prediction, gate, market, date, or environment evidence.

## Remaining Work

- None for this completed Work Package.

## Post-Merge Verification

- Main Project tests `30060574075`: all jobs and Test gate passed.
- GitHub Pages `30060573707`: build and deployment passed; public status is
  `built` from `main`, and the site returns HTTP 200.
- Vercel Production `dpl_HN6RSztSXDD6Qy14Sa5J5Yx6h6sH`: READY, exact merge
  SHA, production target, HTTP 200, and no runtime errors in the one-hour scan.
- Daily Research `30060574102`: PASS no-op at aligned/target `2026-07-20`,
  `markets=[]`; no publication stage ran.
- Resolver evidence: TWSE run 12 has 1,068 predictions and 8,544 gates; TPEx
  run 10 has 863 predictions and 6,904 gates; both are `RESEARCH_ONLY`.
- Recovery controller `30060603248` completed successfully without a rerun.
- Live TWSE/TPEx APIs return HTTP 200, horizon 5, validated
  `2026-07-20`, `decision_at=2026-07-20T17:00:00+08:00`,
  `RESEARCH_ONLY`, exact venue scope, and `Cache-Control: no-store,max-age=0`.

## Key Decisions

- Resolve the newest valid aligned trading date; never substitute the calendar
  date.
- Treat an already-current Production snapshot as an explicit successful no-op.
- Reuse the existing import and Daily Research paths instead of duplicating
  publication, retry, ranking, or validation logic.

## Validation Already Passed

- Focused affected tests: 112 passed.
- Ruff and actionlint passed; basedpyright: 0 errors, 0 warnings.
- Complete quality/security suite and `git diff --check` passed.
- Full: 1,114 Python and 66 Playwright tests passed.
- Independent final review found zero findings at every severity.
- Final PR head and all post-merge deployment checks passed.

## Public Contracts

- Horizon 5 only; other horizons remain `UNSUPPORTED_HORIZON`.
- Ranking remains the sole final ranking source.
- TWSE/TPEx and ETF/common-stock partitions remain isolated.
- `available_at <= decision_at`, `RESEARCH_ONLY`, `HARD_FAIL`, no look-ahead,
  no survivorship bias, and no-placeholder policies remain unchanged.

## Known Issues or Blockers

- No implementation or release blocker.
- A valid no-op means the newest aligned, complete Production snapshots are
  already current; it must not be replaced with today's calendar date.

## Commit and Pull Request References

- Pull Request: https://github.com/migao2006/tool/pull/102
- Merge commit: `53d16233c1ffd494ccb18cc5b53ec550585f8689`
- Feature head: `6c856910260b243bf81ee26261351c8012ab181b`
- Daily Research: https://github.com/migao2006/tool/actions/runs/30060574102

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
