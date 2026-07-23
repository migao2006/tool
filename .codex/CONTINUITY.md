# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: COMPLETE
- Outcome: Production stale-snapshot repair plus persistent
  failure/misalignment reporting and bounded current-main-only recovery.
- Record:
  `tasks/completed/2026-07-24-add-bounded-daily-pipeline-recovery.md`.

## Current Branch

- `codex/add-daily-pipeline-recovery`
- Authoritative base: merged `origin/main` at
  `35bc3560359ebbcac85520b93a3120f4a630ca08`.

## Verified Production State

- Feature-branch Production reconciliation `30033947665` succeeded at exact
  head `94013ba` without forcing a date.
- Resolver selected only incomplete TWSE at aligned date `2026-07-20`;
  current-bars, features, catalog, Staging, Production, and verification passed.
- Live TWSE/TPEx APIs both return validated `2026-07-20`,
  `decision_at=2026-07-20T17:00:00+08:00`, horizon 5, `RESEARCH_ONLY`, and
  `no-store`.
- Deployed Pages source displays the validated snapshot fields and uses an
  uncached API request; no service worker is registered.

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
- Focused (128), Full (1,086 Python + 66 Playwright), lint, type, diff, Fast,
  actionlint, pin/lock, and independent review all passed.

## Remaining Work

- Push this terminal task record, wait for latest PR checks, mark PR #101 ready.
- Stop before protected `main`; a separate final main-update authorization is
  required after this Work Package.

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
- Production run and live API/deployed-source verification passed.

## Known Issues or Blockers

- 2026-07-23 was not a valid joint source date (TWSE `2026-07-22`, TPEx
  `2026-07-23`); serving validated `2026-07-20` is therefore correct.
- Browser-controller infrastructure could not initialize its local kernel
  assets; live API/deployed source plus 66 Playwright tests provide verification.
- No implementation blocker. Protected `main` is intentionally unchanged.

## Commit and Pull Request References

- Base: `35bc3560359ebbcac85520b93a3120f4a630ca08`.
- Original Bug PR: https://github.com/migao2006/tool/pull/100
- Recovery Bug PR: https://github.com/migao2006/tool/pull/101
- Production reconciliation:
  https://github.com/migao2006/tool/actions/runs/30033947665
- Implementation head: `94013baf7880a4ed6334d85c04575b43005e0f1a`.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
