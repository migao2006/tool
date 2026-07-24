# Restore authoritative Decision Policy evidence
## Status
ACTIVE
## Authorization
`FULL_AUTONOMY_UNTIL_MAIN_UPDATE`
## Primary Outcome
Restore the smallest complete, authoritative, point-in-time-safe data path for the
TWSE horizon-5 Decision Policy's required tradability, market-exposure, and
position-limit evidence. Rows with complete, valid evidence may become
`EVALUATED`; every row without trustworthy required evidence must remain
`MISSING_REQUIRED_DATA` with `decision=null` and `system_status=RESEARCH_ONLY`.
## Background
- Work starts from a clean isolated clone on
  `codex/restore-decision-policy-evidence`, based exactly on `origin/main` at
  `e2ba3f54e6086082b72775a326a5fef2f54b43fb`.
- Pull Request #104 is merged. Read-only verification found all 38 migrations,
  including `20260724044115_decision_policy_status_semantics`, applied to both
  Staging and Production. Its Production Edge deployment and public contract are
  live.
- The latest Production TWSE horizon-5 run observed at task start is run 13,
  `as_of_date=2026-07-23`, with 1,067 rows:
  `MISSING_REQUIRED_DATA=1,067`, every action null, and no hard-fail candidate.
- The live Production API remains `RESEARCH_ONLY`, keeps TWSE and TPEx isolated,
  and rejects horizon 2 as `UNSUPPORTED_HORIZON`.
- The current research publisher records eight gates per row but reports missing
  formal tradability, market-exposure, and position-limit inputs.
## Subtasks
1. Inventory ranking rows, prediction runs, market predictions, research
   publishers, Decision Policy inputs, database/RPC/Edge/API serializers,
   workflows, fixtures, and frontend status consumers.
2. Produce a written evidence matrix for tradability, market exposure, and
   position limits covering authority, provenance, representation, effective date,
   `available_at`, market scope, history, null/stale behavior, rejection rules, and
   the first proven missing-data root cause.
3. Inspect Production through read-only interfaces and capture before counts and
   representative complete/incomplete evidence without exposing secrets.
4. Add characterization and contract tests before changing behavior.
5. Implement the smallest authoritative producer, normalization, persistence, and
   transport path that can safely populate evidence; leave unobtainable evidence
   explicitly missing.
6. Enforce freshness, availability, identity, market, source, publication/run, and
   validation semantics and migrate direct callers.
7. Verify Python, database, Edge, API, frontend, publisher, workflow, migration,
   deployment, backfill, and rollback behavior without formula drift.
8. Update direct documentation, release evidence, continuity, and this task;
   commit logically, push the feature branch, open a ready Pull Request, repair CI,
   and execute the repository release path through Production verification.
## Allowed Scope
- Data ingestion, point-in-time normalization, provider adapters, immutable
  provenance, and directly related research artifact boundaries.
- Decision Policy inputs and direct ranking-to-policy publication boundaries.
- Supabase schemas, additive migrations, validation snippets, RPCs, Edge functions,
  API serializers, and read/publish repositories.
- Direct prediction publishers, workflows, deployment/recovery paths, and
  authoritative backfills.
- Frontend consumption of the existing status/action contract.
- Characterization, contract, regression, integration, migration, Edge, workflow,
  frontend, and release verification tests and fixtures.
- Direct documentation, release-manifest sources/generated records, task records,
  and continuity.
## Prohibited Changes
- Rank ordering, ranking models, Rank Score, probability, P10/P50/P90, quantile,
  gate-threshold, or model-formula changes.
- A frontend final score, lowered gates, fabricated candidates, placeholders,
  inferred position limits, or broad defaults that convert unknown evidence into
  valid evidence.
- Present-day identity used as historical truth, current evidence substituted for
  historical decisions, silent cross-market fallback, or TWSE/TPEx mixing.
- Unrelated product features, model retraining, broad architecture cleanup,
  brokerage/trading integration, or another major subsystem.
- Updating, merging, rebasing, fast-forwarding, force-pushing, or arranging an
  asynchronous update of `main` or another protected branch.
## Public Contracts
- Policy actions remain `CANDIDATE`, `WATCH`, and `NO_TRADE`.
- Evaluation statuses remain `EVALUATED`, `MISSING_REQUIRED_DATA`,
  `VALIDATION_FAILED`, and `HARD_FAIL`.
- Only `EVALUATED` carries an action. Missing required evidence produces
  `MISSING_REQUIRED_DATA` and `decision=null`.
- `NO_TRADE` means a complete valid evaluation with at least one applicable
  non-hard gate failure; it never means missing data.
- `HARD_FAIL` never produces `CANDIDATE`. A non-empty fully evaluated universe may
  produce zero candidates; an empty policy universe cannot pass validation.
- Horizon 5 is the only formal horizon. Others return `UNSUPPORTED_HORIZON`.
- The ranking model remains the sole ordering source; the frontend does not create
  a second score.
- `available_at <= decision_at` is mandatory and auditable. TWSE, TPEx, common
  stock, and ETF evidence remain isolated.
- Formal outputs remain `RESEARCH_ONLY` until Production verification is complete;
  this Work Package does not authorize promotion to `PASS`.
## Risk Classification
HIGH. This package changes point-in-time financial evidence, shared data contracts,
schema/migration and Production publication paths. An error could create
look-ahead bias, survivorship bias, cross-market contamination, or a false formal
policy action.
## Validation Plan
- Focused Decision Policy and all three evidence-flow characterization/contract
  suites after each substantive repair.
- Clean database reconstruction, migration-chain apply, migration contract,
  backfill invariance, security/privilege, rejection, and rollback checks.
- Ruff, basedpyright, repository Python lint/type checks, Deno check/fmt/lint/tests,
  Biome/frontend lint/tests, Playwright where affected, and actionlint/static
  workflow validation.
- `python scripts/check_agents_length.py`, `git diff --check`, complete diff/status/
  untracked/secret review, and repository dependency/security checks.
- `pwsh -File scripts/verify-fast.ps1` and
  `pwsh -File scripts/verify-full.ps1`.
- Independent read-only review with High/Medium findings repaired.
- Pull Request CI plus Staging and Production migration, deployment, backfill, API,
  market-isolation, horizon, representative-row, status/action-count, provenance,
  and formula-invariance verification.
- Do not rerun an expensive passing suite unless a later change can affect it.
## Stop Conditions
- The next operation would update `main` or another protected branch.
- Completion requires an unrelated second major subsystem or an unauthorized
  public-contract change.
- Trustworthy evidence is unobtainable and no safe fail-closed implementation
  remains.
- A major old/new behavior difference, look-ahead bias, survivorship bias, or
  security leak cannot be resolved safely.
- Existing user changes cannot be isolated, the diff cannot remain reviewable, or
  required external access is unavailable.
- Five substantive repair cycles are exhausted.
## Definition of Done
- All three evidence categories have documented authoritative semantics and first
  proven root causes.
- Existing usable evidence is connected end to end and unavailable evidence stays
  explicitly missing.
- Formal policy evaluation occurs only for complete, fresh, market-correct,
  point-in-time-valid evidence and all fail-closed contracts remain intact.
- Required focused, migration, static, Fast, Full, security, review, CI, Staging,
  and Production verification passes.
- Production counts and representative provenance show no invalid action/status
  combinations and no ranking/model-formula drift.
- Documentation, continuity, task results, migration/deployment/backfill/rollback
  evidence, logical commits, feature-branch push, and a ready green Pull Request
  are complete.
- Only the protected-branch update remains.
## Results
- Initial gates passed as recorded in Background. A final fetch on 2026-07-24
  confirmed local `main`, `origin/main`, and this branch's merge base remain
  `e2ba3f54e6086082b72775a326a5fef2f54b43fb`.
- The written matrix in `docs/decision-policy-required-evidence.md` records
  authority, existing producer/consumer/storage paths, point-in-time rules,
  market scope, history, missing/stale behavior, rejection, and first root cause
  for all three categories.
- Tradability has partial official venue snapshots, but no exact-date complete
  evidence for the observed Production decision. Venue-coupled profile-date
  resolution blocked otherwise independent imports, observations can arrive after
  the 17:00 decision, `full_cash_delivery_flag` has no independent source, and
  daily inference discarded the partial data.
- Market-exposure model components and the `market_predictions` consumer table
  existed, but no trained/versioned exact-date producer or atomic research
  publication path existed. Production has zero market-prediction rows.
- Position-limit evidence was never produced: there is no point-in-time
  portfolio/allocation state, versioned policy publication, or evidence table.
  Configuration limits cannot prove a proposed allocation passed.
- Added the immutable hashed
  `decision-policy-required-evidence.v1` artifact, exact feature-universe exporter,
  validated inference adapter, audit gate envelope, Python/API/frontend/Edge
  validation, and an additive atomic market-evidence publisher migration.
- Repaired security import scheduling so TWSE and TPEx resolve independently.
  Unavailable, incomplete, stale, future, identity-mismatched, or cross-market
  evidence remains explicitly missing; no historical values were backfilled.
- Characterization tests were added before each behavior repair. The final local
  affected suite passed 86 tests. `just quality` passed Ruff, basedpyright,
  pre-commit, Biome, 64 Edge/Deno tests, actionlint, gitleaks, pip-audit, migration
  contracts, and SQLFluff. `just full` passed 1,171 Python tests and 68 Playwright
  tests. Clean PostgreSQL 17 reconstruction of all 39 migrations, validation,
  privilege, idempotency/conflict, rollback, and re-apply checks passed.
- Final `git diff --check` and independent read-only review passed with no
  remaining High or Medium findings. Rank, Rank Score, probabilities, quantiles,
  gate thresholds, and model formulas were not changed.
- Pull Request #106 is ready and its latest head CI is green: 1,172 Python tests,
  68 Playwright tests, 64 Edge tests, quality/security, Vercel, and aggregate test
  gate passed. The first CI failure was a required CONTINUITY heading and was
  repaired with one focused test.
- Staging now records all 39 Repository migrations. The additive RPC passed its
  privilege, atomicity, missing-evidence, idempotency, conflict, and rollback-safe
  validation; Edge v23 deployed from workflow run `30087314367`, and public API
  smoke/contract verification passed.
- The first Staging deploy encountered an external Edge Runtime image rate limit.
  The workflow now uses the official Management API bundler; its regression test,
  action pin check, actionlint, retry deployment, and latest PR CI passed.
- Post-deploy Staging and read-only Production both report TWSE 1,067 and TPEx 854
  horizon-5 rows, all `MISSING_REQUIRED_DATA`, all actions null, zero hard-fail
  candidates, no market row, and `RESEARCH_ONLY`; horizon 2 is
  `UNSUPPORTED_HORIZON`. Representative ranks, probabilities, and P50 values
  match, so no model-output drift was observed.
- Production remains at 38 migrations and was not mutated. Its migration, Edge
  deployment, immutable missing-evidence republication, and final verification
  require the next operation to update protected `main`; this is the authorized
  stop boundary.
