# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE at the protected-branch boundary; feature work, PR CI, and
  Staging rollout are complete.
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
- Head: `5784312e5c338298c12b9f3f85c4064570d8e560`.
- Ready Pull Request:
  [#106](https://github.com/migao2006/tool/pull/106).

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
- Latest PR CI: 1,172 Python, 68 Playwright, 64 Edge, quality/security, Vercel,
  and aggregate test gate all PASS.
- Staging: 39 migrations, Edge v23 ACTIVE, workflow `30087314367`, RPC validation
  and public API smoke/contract PASS.

## Remaining Work

- Production remains at 38 migrations and unchanged. Updating protected `main` is
  the next operation and needs the only additional authorization; afterward run
  the gated Production migration, Edge deploy, immutable republication, and
  verification.

## Known Issues or Blockers

- No implementation or CI blocker is known.
- GitHub's branch-protection API currently reports no configured protection for
  `main`; the user's explicit protected-branch boundary still governs.

## Commit and Pull Request References

- Commits: `405e828`, `df5a57a`, `1e3b6ce`, `c92d7ab`, `8bae944`, `5784312`.
- Staging deployment:
  [run 30087314367](https://github.com/migao2006/tool/actions/runs/30087314367).
- No protected-branch update or Production data write has been performed.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
