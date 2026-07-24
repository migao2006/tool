# Codex Continuity

This file is a concise cross-session handoff. It records state, not authorization,
and must not replace `tasks/active/TASK.md` or completed reports.

## Current Work Package

- Status: ACTIVE.
- Outcome: audit and correct end-to-end Decision Policy status semantics.
- Active record: `tasks/active/TASK.md`.
- Authorization: `FULL_AUTONOMY_UNTIL_MAIN_UPDATE`; protected branches remain
  unchanged.

## Current Branch

- Branch: `codex/decision-policy-status-semantics`.
- Exact base: `origin/main` at
  `e089c4cb25f26414574082e3e9128b60ab530bdd`.
- Isolated clone; the separate Manual full update repair checkout and branch have
  not been modified.
- Pull Request: not created yet.

## Completed Work

- Latest TWSE horizon-5 run is `prediction_run_id=12`,
  `as_of_date=2026-07-20`, with 1,068 stock rows.
- Persisted and public counts are `CANDIDATE=0`, `WATCH=0`,
  `NO_TRADE=1,068`, hard fail 0.
- All 1,068 rows lack formal tradability, market-exposure, and position-limit
  inputs; the run has no `market_predictions` row.
- All 1,068 persisted stock quality values are `FAIL`, while the public mapper
  reinterprets them as research `WARN` through a reason-code compatibility rule.
- Representative rank-1 symbol `6515` has valid rank/probability/quantile output,
  eight auditable gates, missing mandatory formal policy inputs, and no market
  regime or exposure cap.
- The pre-fix research adapter, serializer, Supabase payload builder, and run
  publisher hard-coded `NO_TRADE` and every research row into
  `no_trade_count`.
- Missing formal inputs remain visible only in gate/reason detail, so persistence,
  counts, API decisions, filters, and badges collapse “policy unavailable” into a
  valid no-action decision.
- The pre-fix publisher also collapses research `WARN` into persisted `FAIL`; the Edge
  mapper reverses that collapse heuristically.
- Core policy, publisher, schema/RPC, Edge API, aggregation, frontend, direct
  daily-publish checks, release metadata, and documentation are corrected.
- Formal `PASS` requires a non-empty policy universe; a non-empty fully evaluated
  universe may still correctly have zero candidates.

## Remaining Work

- Commit and push the reviewed change set, create the Pull Request, resolve PR CI,
  then archive the completed task without updating a protected branch.

## Key Decisions

- Preserve `CANDIDATE`, `WATCH`, and `NO_TRADE` as decision actions.
- Add a separate policy-evaluation status so evaluated decisions, missing required
  inputs, validation failure, and hard fail remain distinct; unsupported horizon
  continues as a fail-closed transport error.
- A missing/invalid/hard-fail policy status must not carry a valid decision.
- `NO_TRADE` will mean only a completed, valid policy evaluation advised no trade.

## Validation Already Passed

- Focused policy/API/frontend/migration tests, 60 Edge/Deno tests, Ruff,
  basedpyright, Biome, actionlint, dependency/secret scans, migration contracts,
  SQLFluff parsing/lint, Fast verification, and `git diff --check` pass.
- Final Full verification passes with 1,149 Python tests and 68 Chromium/WebKit
  Playwright tests.
- The new migration passed a disposable PostgreSQL 17 full migration-chain apply,
  explicit/legacy publisher reads, legacy backfill invariance, privilege, and
  constraint tests across all 38 migrations; no remote database was modified.
- Final independent read-only review: PASS, with no remaining High or Medium
  findings.

## Known Issues or Blockers

- No external blocker. Production deployment remains intentionally unperformed.

## Commit and Pull Request References

- No commit, push, deployment, Pull Request, or protected-branch update yet.

## Maintenance

- Replace stale state at meaningful handoffs; do not append logs or full history.
- Keep this file under 100 physical lines and 12 KiB.
