# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE
- Outcome: Fix the first production boundary preventing automatic publication
  and display of the newest valid research snapshot.
- Active record: `tasks/active/TASK.md`.

## Current Branch

- `codex/fix-stale-research-snapshot`
- Authoritative base: `origin/main` at
  `efa71b56b65d937f0063f4100606f164d274e4ae`.

## Verified Production State

- PR #97 is merged; Project tests, Vercel Production, and GitHub Pages passed.
- Daily Research run `30009209231` resolved and published current bars for
  `2026-07-20`.
- TWSE and TPEx feature artifacts passed; TPEx staging publication passed.
- TWSE staging publication failed; Production publication was skipped.
- Production API still returns `2026-07-17` for both venues with no-store
  caching; static deployments contain the current frontend.

## Completed Work

- Proved the first stale boundary is TWSE staging publication: all 1,068
  production-symbol identities were unresolved in the isolated staging project.
- Added a validated, ID-free production security catalog and staging-local
  identity synchronization before inference publication.
- Added frontend background revalidation and GitHub Pages CORS coverage.
- Focused tests, lint, type checks, Edge tests, quality, diff checks, and Fast
  verification pass.
- Full verification passes with 1,011 Python and 66 Playwright tests.
- Independent read-only review found zero blockers.
- Production Edge deployment run `30015976124` succeeded on retry; GitHub Pages
  GET/OPTIONS now pass exact-origin CORS with no-store.

## Remaining Work

- Commit, push, open a Bug PR, validate Staging publication, and wait for green
  CI.
- Archive the terminal task and restore the active-task sentinel.
- Stop before updating `main`.

## Key Decisions

- Transfer semantic identity fields only; never copy production surrogate IDs.
- Preserve market and common-stock isolation, point-in-time rules, horizon 5,
  ranking semantics, `RESEARCH_ONLY`, and all fail-closed publication gates.
- Treat frontend revalidation and GitHub Pages CORS as directly related
  end-to-end freshness defects, not as the primary stale boundary.

## Validation Already Passed

- Focused backend/frontend/workflow/publication/snapshot tests: passed.
- Playwright characterization and regression tests: 20 passed.
- Edge Function checks and tests: 47 passed.
- Repository quality suite and Fast verification: passed.
- Final Full verification: 1,011 Python and 66 Playwright tests passed.

## Known Issues or Blockers

- No current blocker.

## Commit and Pull Request References

- Base: `efa71b56b65d937f0063f4100606f164d274e4ae`.
- Production failure: https://github.com/migao2006/tool/actions/runs/30009209231
- Bug PR: not yet created.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
