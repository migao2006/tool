# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: COMPLETE
- Outcome: Production stale-snapshot repair and bounded daily recovery are
  merged, deployed, and verified on `main`.
- Record:
  `tasks/completed/2026-07-24-record-daily-pipeline-recovery-main-release.md`.

## Current Branch

- `main`
- PR #101 release merge:
  `2525001ad47700682de90bbc0de6246cdb378625`.
- Implementation head:
  `d50b60a76e86e234e5d14de9f672e01587d74e0e`.

## Verified Production State

- PR #101 is merged. Main Project tests `30051830601`, Pages deployment
  `30051829711`, Daily Research `30051830757`, and recovery controller
  `30051865693` all completed successfully at the exact release merge.
- Vercel deployment `dpl_F7idY3QB9zNBfk7wuP2KNNkEGYN5` is READY,
  Production-targeted, and bound to the exact release merge; the one-hour
  post-deploy runtime error scan was clean.
- Main Daily Research resolved aligned `2026-07-20`, found both markets already
  complete, and correctly no-op'd. The main recovery controller then completed
  without requesting an unnecessary rerun.
- Live TWSE/TPEx APIs both return validated `2026-07-20`,
  `decision_at=2026-07-20T17:00:00+08:00`, horizon 5, `RESEARCH_ONLY`, and
  `no-store`.
- GitHub Pages and Vercel Production both return HTTP 200.

## Completed Work

- Proved repeated TWSE REST reads crossed the fixed 30-second client timeout.
- Proved partial TWSE run 11 had 1,068 predictions but zero of 8,544 gates; API
  failed closed, while the old date-only resolver would have skipped repair.
- Added 60-second, exact-connection-error-only bounded publish/read recovery.
- Resolver now requires complete rows, counts, venue/status, and all eight gates
  per prediction before a market is current.
- Added sanitized deterministic Issues and bounded full reruns for trusted,
  current-main-only import mismatch or verified transient Daily failures.
- Attempt-qualified artifacts prevent immutable rerun evidence collisions.
- Import runs at 19:45 Asia/Taipei on weekdays. A successful import triggers
  Daily Research, with a weekday 21:15 fallback schedule.
- Focused (128), Full (1,086 Python + 66 Playwright), lint, type, diff, Fast,
  actionlint, pin/lock, and independent review all passed.

## Remaining Work

- None for this release.

## Key Decisions

- Never compare freshness with today's date. Select only the newest valid,
  aligned, fully published snapshot.
- Import mismatch: four in-job checks plus at most one full rerun.
- Daily timeout: at most three total attempts. Other Daily failures rerun only
  from exact allowlisted artifacts proving sole `SUPABASE_CONNECTION_ERROR`.
- Stale, untrusted, malformed, mixed, or permanent failures remain report-only.

## Validation Already Passed

- PR implementation-head Project tests, Test gate, frontend/browser,
  quality/security, Vercel, and Preview checks passed.
- Final independent review: zero BLOCKER/HIGH/MEDIUM/LOW findings.
- Post-merge main Project tests, Vercel Production, GitHub Pages, Daily
  Research, recovery controller, and live API verification passed.

## Known Issues or Blockers

- 2026-07-23 was not a valid joint source date (TWSE `2026-07-22`, TPEx
  `2026-07-23`); serving validated `2026-07-20` is therefore correct.
- Browser-controller infrastructure could not initialize its local kernel
  assets; live API/deployed source plus 66 Playwright tests provide verification.
- No implementation, deployment, migration, or authorization blocker remains.

## Commit and Pull Request References

- Release merge: `2525001ad47700682de90bbc0de6246cdb378625`.
- Original Bug PR: https://github.com/migao2006/tool/pull/100
- Merged recovery Bug PR: https://github.com/migao2006/tool/pull/101
- Production reconciliation:
  https://github.com/migao2006/tool/actions/runs/30033947665
- Post-merge main tests:
  https://github.com/migao2006/tool/actions/runs/30051830601
- Post-merge Daily Research:
  https://github.com/migao2006/tool/actions/runs/30051830757

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
