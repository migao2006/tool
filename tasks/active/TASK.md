# Audit and correct Decision Policy status semantics
## Status
ACTIVE
## Authorization
`FULL_AUTONOMY_UNTIL_MAIN_UPDATE`
## Primary Outcome
Audit and correct the end-to-end Decision Policy status contract so formal candidates,
watch decisions, policy no-action, missing mandatory policy evidence, validation
failure, hard failure, and unsupported horizons remain distinct, fail closed, and
agree across evaluation, persistence, publication, API aggregation, and the frontend.
## Background
- Isolated feature branch: `codex/decision-policy-status-semantics`.
- Exact base: `origin/main` at
  `e089c4cb25f26414574082e3e9128b60ab530bdd`.
- Production evidence records 1,068 ranked TWSE research predictions, all serialized
  as `NO_TRADE`, with 0 hard fails, while the market summary reports unavailable
  market-policy data.
- Repository product policy says `NO_TRADE` is a stock decision and does not mean a
  data error. Mandatory missing evidence must nevertheless fail closed and remain
  visibly distinguishable.
- The separate Manual full update artifact Work Package and its workflow/branch are
  outside this task and must remain untouched.
## Subtasks
1. Inventory ranking output, gate construction, market inputs, policy evaluation,
   persistence, serializers, API aggregation, frontend labels/filters/details, and
   direct tests.
2. Inspect one representative Production prediction, its eight gates and reason
   codes, the market-policy record, and aggregate counts through read-only approved
   interfaces.
3. Add characterization tests, identify the first proven root cause, and define the
   smallest compatible authoritative taxonomy.
4. Correct directly affected backend, persistence/publication, API, and frontend
   callers without changing rank ordering, probabilities, quantiles, or thresholds.
5. Add status/reason contract, aggregate, serialization, integration, rendering,
   filtering, and representative snapshot regression coverage.
6. Run focused checks, Ruff, basedpyright, frontend lint/type checks,
   `git diff --check`, Fast, Full, independent read-only review, and Pull Request CI.
7. Commit logical changes, fetch and reconcile the latest `origin/main`, push the
   feature branch, and create or update a Pull Request.
## Allowed Scope
- `src/decision/` and direct ranking-to-policy integration.
- Directly related prediction publication/persistence contracts, serializers, API
  handlers, status aggregation, and fixtures.
- Frontend overview, candidate lists, status badges, filters, and decision details.
- Directly related tests, documentation, release-manifest source data, task record,
  and continuity record.
- Directly affected CI configuration only if required and outside the prohibited
  Manual full update workflow.
## Prohibited Changes
- `.github/workflows/manual-full-update.yml`, the active Manual full update artifact
  handoff repair, its branch, and unrelated import/recovery workflow logic.
- Ranking formulas, model retraining, prediction probabilities, conditional
  quantiles, thresholds chosen merely to change counts, or a second frontend score.
- Historical identity architecture, unrelated schemas/migrations, broad frontend
  redesign, brokerage/trading integration, fabricated policy values, or broad
  skips/ignores.
- Any update, merge, rebase, fast-forward, direct push, or auto-merge of `main` or
  another protected branch without final explicit authorization.
## Public Contracts
- Horizon 5 is formal; every other horizon returns `UNSUPPORTED_HORIZON`.
- The rank model remains the sole ordering source; the frontend does not calculate a
  second final score.
- `available_at <= decision_at`; TWSE and TPEx remain isolated; COMMON_STOCK and ETF
  paths remain isolated.
- `HARD_FAIL` never becomes `CANDIDATE`; incomplete mandatory evidence fails closed.
- Missing policy evidence must not silently serialize as a valid policy
  `NO_TRADE` unless code and persisted evidence prove that as an explicit tested
  contract.
- Results remain `RESEARCH_ONLY` until formal validation is complete; no guaranteed
  profit or precise future-price claims.
- Traditional Chinese labels must describe the authoritative backend status without
  implying that `NO_TRADE` means no market transactions.
## Risk Classification
HIGH. This changes a shared public status/reason contract and potentially multiple
backend, persistence, API, aggregation, and frontend callers. Incorrect handling can
misrepresent missing mandatory evidence as a valid trading-policy decision.
## Validation Plan
- Characterization and focused Decision Policy, publication, API serialization,
  aggregate-count, snapshot, and frontend rendering/filter tests.
- `uv run --system-certs --extra test pytest <focused affected tests>`.
- `uv run --system-certs ruff check <affected Python paths>`.
- `uv run --system-certs basedpyright <affected Python paths>` or the repository
  configured equivalent.
- Repository frontend lint, type-check, and focused Playwright checks.
- `python scripts/check_agents_length.py`.
- `git diff --check` plus full diff/status/untracked/secret inspection.
- `pwsh -File scripts/verify-fast.ps1`.
- `pwsh -File scripts/verify-full.ps1`.
- Independent read-only review and Pull Request CI.
## Stop Conditions
- Updating `main` or another protected branch is the next operation.
- Completion requires a second unrelated major subsystem or an unauthorized public
  contract change.
- Production evidence exposes an unresolvable semantic ambiguity or required
  external access is unavailable.
- Existing user work cannot be safely isolated.
- Five substantive repair rounds are exhausted without safe progress.
- A security leak, look-ahead bias, survivorship-bias regression, or materially
  unexplained behavior difference is confirmed.
## Definition of Done
- `NO_TRADE` has one explicit, tested meaning and is not conflated with missing data.
- The cause of all 1,068 published `NO_TRADE` rows is proven and documented.
- Evaluation, persistence, API, counts, labels, filters, and details agree; useful
  reason codes are exposed safely.
- Missing market-policy data fails closed visibly, hard fails cannot become
  candidates, counts equal published rows, rank order is unchanged, and unsupported
  horizons remain fail closed.
- Required focused/static/Fast/Full/review/CI validation passes.
- The feature branch is committed, reconciled with latest main if needed, pushed,
  and represented by a ready green Pull Request.
- No protected branch is updated; the package stops at the authorization boundary.
## Results
- Exact isolated base and feature branch are recorded above; the separate Manual
  update repair checkout and branch remain untouched.
- Production read-only evidence verified the latest TWSE horizon-5 run as
  `prediction_run_id=12`, `as_of_date=2026-07-20`, with 1,068 ranked rows,
  no market-policy row, and no hard fail.
- Every row has missing formal tradability, market-exposure, and position-limit
  inputs. Persisted decisions/counts nevertheless report 1,068 `NO_TRADE`.
- First proven root cause: the research adapter, serializer, Supabase payload
  builder, and run counters hard-code `NO_TRADE`; missing inputs survive only as
  reasons/gates. Research `WARN` is separately stored as `FAIL` and heuristically
  converted back by the API.
- Authoritative contract now separates policy action
  (`CANDIDATE`/`WATCH`/`NO_TRADE`) from evaluation status
  (`EVALUATED`/`MISSING_REQUIRED_DATA`/`VALIDATION_FAILED`/`HARD_FAIL`); only
  evaluated rows may carry an action.
- Backend evaluation, research publication, persistence/RPC migration, Edge
  serialization/aggregation, frontend labels/filters/details, daily publish
  verification, fixtures, and direct documentation have been migrated.
- Legacy Production research rows are preserved fail closed: rank/probability/
  quantile values are unchanged, while legacy `NO_TRADE` is reclassified as
  `MISSING_REQUIRED_DATA` with a null action.
- The migration passed a fresh PostgreSQL 17 full-chain apply, explicit and legacy
  publish/read validation, backfill invariance checks, privilege checks, and
  constraint rejection checks in a disposable container. The final rebuild applied
  all 38 migrations and also rejected empty or phantom formal universes.
- Formal `PASS` now requires a non-empty published policy universe while preserving
  the valid case where a non-empty, fully evaluated universe produces zero
  candidates.
- Focused Decision Policy/API/frontend/migration tests, 60 Edge/Deno tests, Ruff,
  basedpyright, Biome, actionlint, gitleaks, pip-audit, SQLFluff, Fast verification,
  1,149 full Python tests, and 68 Playwright Chromium/WebKit tests pass.
- The final independent read-only review passed after verifying the empty-universe
  boundary; it found no remaining High or Medium defects.
- Latest `origin/main` was fetched after implementation and remains the exact base
  SHA, so no reconciliation changes were required. Commit/push/PR-CI remain in
  progress.
