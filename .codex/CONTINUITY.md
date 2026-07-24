# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE
- Outcome: add one owner-triggered, fail-closed full daily update workflow.
- Active record: `tasks/active/TASK.md`.
- Authorization: `FULL_AUTONOMY_UNTIL_MAIN_UPDATE`.

## Current Branch

- Branch: `codex/manual-full-update`.
- Base: `main` / `origin/main`
  `e0bcf074aed92d14dc52e003cd2ea701efd2c2ab`.
- Protected `main` has not been updated by this Work Package.

## Completed Work

- Added `manual-full-update.yml`, dispatch-only with defaults
  `dry_run=false`, `publish_production=true`, blank `as_of_date`.
- Added main/date preflight and named-secret reusable calls into existing Import
  and Daily workflows.
- Dry-run executes Import validation plus Daily resolver without mutation.
- Existing Import and Daily concurrency groups remain active; Manual uses a
  distinct group to avoid reusable caller/callee self-cancellation.
- Resolver now preserves already-computed validated Production run, prediction,
  and gate counts without adding a second database query.
- Final summary composes only sanitized Import, resolver, and Production
  verifier evidence, and fails closed on missing or inconsistent artifacts.
- Existing recovery now recognizes the Manual wrapper, keeps trusted-main
  checks and persistent Issues, and permits at most two total attempts.
- Added workflow/summary/recovery tests and operator documentation.

## Validation Already Passed

- Focused workflow, resolver, import, recovery, and summary tests: 112 passed.
- Ruff and affected actionlint passed; basedpyright: 0 errors, 0 warnings.
- Complete quality/security suite and `git diff --check` passed.
- Fast passed. Full passed: 1,114 Python and 66 Playwright tests.
- Independent final read-only review: zero findings at every severity.
- Commit, push, PR, and CI remain pending.

## Key Decisions

- Never derive snapshot freshness from today's calendar date.
- Missing markets come only from the existing resolver.
- No-op requires complete resolver evidence for both markets.
- Required-market final evidence comes only from the existing Production
  verifier; publish reports are not treated as success evidence.
- Manual failures participate in bounded recovery instead of bypassing the
  existing Issue/reporting controller.
- Horizon 5, ranking, point-in-time, venue/asset isolation, `RESEARCH_ONLY`,
  and `HARD_FAIL` semantics remain unchanged.

## Remaining Work

- Commit and push the implementation, open the PR, and repair CI until green.
- Complete/archive TASK and push the terminal record.
- Stop immediately before protected-main update and ask once for authorization.

## Known Issues or Blockers

- GitHub concurrency retains at most one pending run per group with the pinned
  actionlint-supported syntax; a newer third pending request can replace the
  previous pending request, but cannot overlap mutation.
- Manual workflow cannot be safely Production-executed until merged to `main`;
  PR validation is syntax, contract, and CI only.

## Commit and Pull Request References

- Commit: pending.
- Feature push: pending.
- Pull Request: pending.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
