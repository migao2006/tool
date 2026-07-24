# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE; local implementation and verification are complete.
- Outcome: restore authoritative point-in-time Decision Policy evidence transport
  while preserving fail-closed behavior.
- Active record: `tasks/active/TASK.md`.
- Authorization: `FULL_AUTONOMY_UNTIL_MAIN_UPDATE`; protected branches remain
  unchanged.

## Current Branch

- Branch: `codex/restore-decision-policy-evidence`.
- Exact base and final fetched `origin/main`:
  `e2ba3f54e6086082b72775a326a5fef2f54b43fb`.
- The isolated worktree was clean at task start; all current changes belong to
  this Work Package.
- Feature-branch commits and Pull Request are pending.

## Investigation Result

- Production baseline: TWSE run 13, `as_of_date=2026-07-23`, 1,067 horizon-5
  rows, all `MISSING_REQUIRED_DATA`, all actions null, and `RESEARCH_ONLY`.
- Tradability has partial official venue observations, but no complete exact-date
  pre-decision evidence. Venue coupling blocked imports; observations may be late;
  `full_cash_delivery_flag` remains unsourced; inference dropped partial data.
- Market-exposure components and consumers existed, but no authoritative
  trained/versioned producer or publication path. Production has zero
  `market_predictions`.
- Position limits have no point-in-time portfolio/policy producer or historical
  state. Config values cannot establish a pass.
- Evidence matrix: `docs/decision-policy-required-evidence.md`.

## Completed Work

- Added immutable `decision-policy-required-evidence.v1`, exact feature-universe
  export, strict availability/identity/market/freshness validation, validated
  inference, gate audit transport, and publisher/API/Edge/frontend enforcement.
- Added an additive three-argument atomic publisher RPC for one canonical market
  evidence row plus rollback and validation snippets.
- Made TWSE and TPEx security imports independent. Missing or incomplete official
  data remains missing; no historical value backfill or current-identity
  substitution is allowed.
- Release and rollback procedure:
  `docs/decision-policy-evidence-release.md`.

## Key Decisions

- Only validated `AVAILABLE` evidence may supply formal policy inputs.
- Unavailable evidence remains `MISSING_REQUIRED_DATA` with a null action.
- No historical value backfill, current-identity substitution, default position
  limit, or cross-market fallback is permitted.

## Validation Already Passed

- Affected suite: 86 tests.
- Quality: Ruff, basedpyright, pre-commit, Biome, actionlint, migration contracts,
  SQLFluff, gitleaks, pip-audit, and 64 Edge/Deno tests.
- Full: 1,171 Python tests and 68 Playwright tests.
- PostgreSQL 17 clean reconstruction: all 39 migrations plus validation,
  privileges, idempotency/conflict rejection, rollback, and re-apply.
- `git diff --check` and independent read-only review: PASS; no High/Medium
  findings.

## Remaining Work

- Commit logically, push the feature branch, open a ready Pull Request, and resolve
  CI.
- Apply and verify the additive migration and compatible Edge contract in Staging.
- Re-read Production baseline and document the final protected-branch boundary.
- Production workflow requires `main`; stop before updating that protected branch
  and request the only additional authorization at that point.

## Known Issues or Blockers

- The first PR CI run exposed only a missing required continuity section; the
  documentation-only repair is in progress.
- No implementation blocker is known. Production rollout remains intentionally
  gated on the protected branch.

## Commit and Pull Request References

- Commits: `405e828`, `df5a57a`, `1e3b6ce`, `c92d7ab`.
- Ready Pull Request:
  [#106](https://github.com/migao2006/tool/pull/106).
- No protected-branch update or Production data write has been performed.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
