# Fix stale latest research snapshot publication
## Status
ACTIVE
## Authorization
`FULL_AUTONOMY_UNTIL_MAIN_UPDATE`
## Primary Outcome
Identify and permanently fix the first production boundary that prevents the
overview from displaying the newest valid published five-day research snapshot,
then publish a reviewed Bug PR with green CI without updating `main`.
## Background
- Authoritative base is `efa71b56b65d937f0063f4100606f164d274e4ae`.
- PR #97 merged at that commit; Project tests, Vercel Production, and GitHub
  Pages deployments succeeded.
- Post-merge Daily Research run `30009209231` resolved aligned market data and
  immutable TWSE/TPEx current-bar publications for `2026-07-20`.
- Both feature builds and TPEx staging publication succeeded, but TWSE staging
  publication failed and therefore Production publication was skipped.
- The Production API consequently still serves validated `2026-07-17` snapshots
  for both venues.
## Subtasks
- Reproduce and inspect the failed TWSE staging publication.
- Trace every market-data, feature, inference, snapshot, manifest, publication,
  deployment, API, frontend-selection, and display boundary.
- Characterize the root cause with regression tests.
- Implement the smallest complete upstream fix and repair direct callers.
- Verify cache, calendar, timezone, venue, asset-type, horizon, validation, and
  deterministic latest-snapshot behavior.
- Run focused, frontend, backend, workflow, publication, snapshot, Fast, Full,
  and independent-review gates.
- Commit, push this Bug branch, create a Bug PR, and wait for green CI.
## Allowed Scope
Directly related workflows, scripts, data/research ingestion and publication,
pipeline, Supabase prediction snapshot code, frontend snapshot loading and
selection, deployment synchronization, tests, fixtures, CI, task records,
continuity, and direct callers.
## Prohibited Changes
- Do not reopen or rewrite the completed archive row-adaptation Work Package
  except where direct evidence makes a narrowly related correction necessary.
- Do not hardcode dates, fake freshness, skip validation, weaken fail-closed or
  `HARD_FAIL` behavior, change ranking/decision semantics or horizon support, or
  mix venue/asset partitions.
- Do not introduce look-ahead, survivorship, or `available_at > decision_at`.
- Do not merge the Bug PR or otherwise update protected `main`.
## Public Contracts
- Only horizon 5 is supported; other horizons return `UNSUPPORTED_HORIZON`.
- Rank model remains the sole ordering source; frontend computes no final score.
- Snapshot and decision dates come only from the validated selected snapshot.
- Latest-valid selection remains deterministic and fail closed.
- TWSE/TPEx and ETF/common-stock data remain isolated.
- `available_at <= decision_at`, historical identity policy, `RESEARCH_ONLY`,
  and `HARD_FAIL` semantics remain unchanged.
## Risk Classification
HIGH: the defect crosses automated production research publication, immutable
artifacts, database manifests, an Edge API, and two static deployment targets;
an incorrect repair could publish stale or point-in-time-invalid research data.
## Validation Plan
- Add focused characterization/regression tests for the proven stale boundary.
- Run affected backend, frontend, workflow, publication, and snapshot tests.
- Run pinned Ruff/lint and basedpyright/type checks for affected scope.
- Run `python scripts/check_agents_length.py`, `git diff --check`, and inspect
  final status/diff/untracked/generated/secrets evidence.
- Run `pwsh -File scripts/verify-fast.ps1`.
- Run `pwsh -File scripts/verify-full.ps1` because shared publication contracts
  and PR readiness are in scope.
- Obtain an independent read-only review before publication.
- Verify PR CI and the final deployed/served artifact appropriate to the branch.
## Stop Conditions
- Mark PARTIAL if a valid latest snapshot cannot be advanced without changing a
  prohibited public contract or an unavailable external credential/service.
- Mark BLOCKED only after the repository-defined repeated-blocker threshold is
  met and no safe in-scope progress remains.
- Stop after green Bug PR CI, immediately before any update to `main`.
## Definition of Done
- The production symptom and first stale boundary are proven end to end.
- A regression test fails before and passes after the smallest complete fix.
- The newest valid snapshot advances automatically without fake dates or
  contract drift, and production/API/frontend evidence agrees.
- Focused, lint, type, diff, Fast, Full, and independent review pass.
- Task records are terminal and archived; branch is committed and pushed.
- Bug PR exists with green CI; `main` remains untouched after PR creation.
## Results
- Reproduced the stale Production API and proved the first stale boundary:
  Daily Research run `30009209231` generated valid `2026-07-20` TWSE/TPEx
  features and inference artifacts, but all 1,068 TWSE symbols were unresolved
  in isolated Staging, so its manifest was not written and Production was
  correctly skipped.
- Added a deterministic, hashed, `RESEARCH_ONLY` production security catalog
  containing semantic identity only, followed by validated Staging-local source
  and security ID synchronization before inference.
- Preserved horizon 5, ranking, decision, point-in-time, venue/asset isolation,
  historical identity, and fail-closed contracts.
- Added background snapshot revalidation and repaired GitHub Pages CORS
  synchronization; Production GET/OPTIONS now return 200/204 for the Pages
  origin with exact ACAO and `no-store`.
- Focused tests, lint, type checks, Edge checks (47 passed), quality/security,
  `git diff --check`, Fast verification, and Full verification (1,011 Python +
  66 Playwright) pass.
- Final independent read-only review found zero blockers and judged the
  implementation mergeable.
- Remaining: commit/push, Staging end-to-end run, Bug PR, green CI, terminal
  task archive, and stop before updating `main`.
