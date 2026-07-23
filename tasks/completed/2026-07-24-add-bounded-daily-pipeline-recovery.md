# Add bounded daily pipeline recovery and reporting
## Status
COMPLETE
## Authorization
`FULL_AUTONOMY_UNTIL_MAIN_UPDATE`
## Primary Outcome
Permanently repair the production path that left the overview on an old
research date, then add persistent reporting and bounded, current-main-only
automatic recovery for eligible daily import and research failures without
weakening any publication or point-in-time contract.
## Background
- The authoritative implementation base is merged `main` commit
  `35bc3560359ebbcac85520b93a3120f4a630ca08`.
- Live 2026-07-23 market sources were not aligned: TPEx was `2026-07-23` and
  TWSE was `2026-07-22`. Therefore 2026-07-23 was not a valid joint research
  date; the newest valid aligned date was `2026-07-20`.
- Main Daily Research run `30021481019` advanced TPEx Production to
  `2026-07-20`, but TWSE failed at the Data API read boundary.
- Follow-up runs again reached TWSE feature or Production reads and failed with
  the exact sanitized reason `SUPABASE_CONNECTION_ERROR`.
- One failed TWSE Production attempt committed run 11 and 1,068 predictions but
  stopped before writing its 8,544 decision gates. The public API correctly
  rejected that partial publication.
- The old daily resolver considered only the latest prediction-run date, so the
  incomplete run would make later schedules incorrectly no-op forever.
## Subtasks
- Trace market data, current-bar publication, both feature builds, inference,
  snapshot, manifest, artifact, deployment, API, frontend selection, and
  displayed dates to the first stale boundary.
- Characterize the fixed 30-second Data API timeout and incomplete-publication
  resolver behavior with regression tests.
- Add bounded retry for immutable stored-snapshot publication and Production
  resolver reads only for the exact connection-error reason.
- Require complete latest Production rows and all eight decision gates before a
  market is considered current.
- Persist sanitized import/research failure reports and recover only trusted
  current-main runs within deterministic attempt limits.
- Isolate immutable workflow artifacts by `github.run_attempt`.
- Run focused, lint, type, workflow, publication, snapshot, Fast, Full, and
  independent-review gates; push a feature branch and prepare a green Bug PR.
## Allowed Scope
Directly related workflows, import/research scripts, publication and resolver
contracts, tests, task records, continuity, and direct callers.
## Prohibited Changes
- Do not hardcode dates, compare freshness to the current calendar date, fake a
  snapshot date, bypass validation, or force publication of misaligned sources.
- Do not change ranking or decision semantics, horizon support, venue or asset
  isolation, point-in-time rules, historical identity, `RESEARCH_ONLY`, or
  `HARD_FAIL`.
- Do not retry stale-SHA, untrusted, cancelled, permanent, mixed, malformed, or
  unsupported failures.
- Do not update protected `main` without a separate final authorization after
  this Work Package's PR is green.
## Public Contracts
- Horizon 5 remains the only official horizon; all others remain
  `UNSUPPORTED_HORIZON`.
- The ranking model remains the sole final ranking source.
- The displayed snapshot and decision dates come only from the validated
  published snapshot.
- Latest-valid selection remains deterministic and fail closed.
- TWSE/TPEx and ETF/common-stock partitions remain isolated.
- `available_at <= decision_at`, historical identity, `RESEARCH_ONLY`, and
  `HARD_FAIL` policies remain unchanged.
## Risk Classification
HIGH: the changes affect privileged workflow recovery and Production research
publication. Incorrect trust checks, retry limits, or completeness rules could
create loops, execute stale code, or expose an invalid snapshot.
## Validation Plan
- Run combined recovery, workflow, ingestion, resolver, stored publication, and
  snapshot characterization/regression tests.
- Run Ruff, basedpyright, actionlint, action-pin and lock checks.
- Run `git diff --check`, Fast verification, and Full verification.
- Obtain an independent read-only review.
- Run a feature-branch Production reconciliation without forcing a date, then
  verify the final live Edge API and deployed GitHub Pages source contract.
- Push the terminal record, wait for the latest PR checks, and stop before
  updating protected `main`.
## Stop Conditions
- Mark PARTIAL if repair requires weakening a prohibited contract or an
  unavailable production credential.
- Mark BLOCKED only after the repository-defined repeated-blocker threshold and
  no safe in-scope alternative remains.
- Stop after a green, ready Bug PR and terminal production evidence, immediately
  before any protected-main update.
## Definition of Done
- The production symptom and first stale boundary are reproduced and proven.
- The smallest complete repair automatically reconciles an incomplete latest
  publication without inventing a calendar date.
- Eligible failures/misalignment are persistently reported and only verified
  transient current-main failures receive bounded reruns.
- Focused, lint, type, diff, Fast, Full, and independent review pass.
- A Production reconciliation and both live market APIs prove the newest valid
  aligned snapshot.
- Task records are terminal, the feature branch is pushed, and the Bug PR is
  green and ready without updating `main`.
## Results
- Proved the first new stale boundary was TWSE Production Data API reading:
  repeated client failures occurred about 31 seconds after requests began,
  matching the original 30-second timeout. A TWSE-only run completed its atomic
  prediction RPC and first read-back before the next read stalled; database
  logs showed no statement-timeout failure.
- Proved the second root layer: run 11 at `2026-07-20` contained 1,068 TWSE
  prediction rows but zero decision gates, while the resolver treated its date
  as current. The Edge API correctly returned
  `RESEARCH_DECISION_GATE_ATTACHMENT_INCOMPLETE`, but future daily schedules
  would have skipped TWSE indefinitely.
- Gave immutable stored-snapshot publication a 60-second Data API timeout and at
  most three whole-publish attempts with 1/2-second backoff, only for the exact
  `SUPABASE_CONNECTION_ERROR`. Every attempt uses a fresh writer and replays the
  same prevalidated, hash-locked snapshot through idempotent contracts.
- Changed latest-valid resolution so a market is current only when its latest
  run has the exact market, horizon 5, `RESEARCH_ONLY`, valid summary counts,
  unique stock rows with the exact venue/status contracts, and eight decision
  gates per prediction. An incomplete latest run is selected for repair.
- Added the same bounded connection-error policy to read-only resolver calls;
  validation errors do not retry.
- Added sanitized PASS/DEFERRED/FAIL import results, attempt-qualified immutable
  artifacts, and a privileged recovery controller. It revalidates repository,
  workflow identity/path, branch, event, server-side run state, attempt, and the
  current default-branch SHA before any write.
- Import source-date mismatch receives four in-job checks and at most one
  delayed full-workflow rerun. Daily timeout is bounded to three total attempts.
  Daily stage failures rerun only when every failed stage is allowlisted and
  every exact attempt artifact proves the sole transient connection reason.
- Unknown, stale-SHA, missing/duplicate/malformed, mixed, permanent, cancelled,
  or state-changing failures remain fail closed and report-only. One
  deterministic GitHub Issue records each source run; success closes it and
  exhaustion remains visible.
- Combined focused tests passed: 128 tests across recovery, workflow,
  ingestion, resolver, stored publication, and snapshot paths.
- Ruff, basedpyright (0 errors/0 warnings), actionlint, immutable Action pins,
  Python locks, `git diff --check`, and Fast verification passed.
- Full verification passed with 1,086 Python tests and 66 Playwright tests.
- Final independent read-only review reported zero BLOCKER, HIGH, MEDIUM, or
  LOW findings.
- Feature-branch Production run `30033947665` used exact head `94013ba`, did
  not force `as_of_date`, and completed successfully. The fixed resolver chose
  only TWSE for repair at aligned date `2026-07-20`; current-bar publication,
  TWSE features, catalog, Staging, and Production all passed.
- TWSE Production run 12 contains 1,068 predictions and all 8,544 gates; TPEx
  remains complete with 863 predictions. Both live APIs now return
  `as_of_date=2026-07-20`,
  `decision_at=2026-07-20T17:00:00+08:00`, horizon 5, and
  `RESEARCH_ONLY`, with `Cache-Control: no-store,max-age=0`.
- Deployed GitHub Pages source displays `snapshot.asOfDate` and
  `snapshot.decisionAt`, requests the Production API with `cache: "no-store"`,
  and contains no service-worker registration. It does not compute or display
  the current calendar date as freshness.
- The result is correctly `2026-07-20`, not 2026-07-23: the latter was not a
  valid aligned TWSE/TPEx snapshot.
- Implementation commits `ecf3a50`, `5951bd7`, and `94013ba` were pushed to
  `codex/add-daily-pipeline-recovery`; Bug PR #101 exists without merge or
  auto-merge. The terminal record commit must be pushed and its checks observed
  before stopping ahead of protected `main`.
