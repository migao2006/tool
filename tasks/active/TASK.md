# Add bounded daily pipeline recovery and reporting
## Status
ACTIVE
## Authorization
`FULL_AUTONOMY_UNTIL_MAIN_UPDATE`
## Primary Outcome
Persistently report failed or source-date-misaligned daily market/research runs
and automatically retry only eligible current-main failures within strict,
auditable limits, without weakening any validation or publication gate.
## Background
- The authoritative implementation base is merged `main` commit
  `35bc3560359ebbcac85520b93a3120f4a630ca08`.
- Import run `30010235104` correctly rejected a `2026-07-23` TPEx versus
  `2026-07-22` TWSE source-date mismatch after four in-job attempts, but only
  Actions logs recorded the exhausted failure and no later import was launched.
- Daily Research currently runs after a successful import and from a weekday
  fallback schedule, but it has no persistent failure issue or bounded
  workflow-level retry controller.
- Superseded scheduled run `30020254516` correctly failed closed when its old
  TPEx model run could not replace a newer Staging run. Such stale-SHA runs
  must be reported as superseded and must never be automatically retried.
- GitHub v4 artifacts are immutable across rerun attempts. Safe complete
  workflow reruns require attempt-qualified upload and download names.
## Subtasks
- Add a sanitized import result contract that distinguishes transient
  source-date mismatch from permanent failures without persisting raw logs,
  secrets, URLs, or large symbol details.
- Add a privileged recovery workflow and a testable controller that validates
  the source repository, workflow identity/path, default branch, current head
  SHA, run ID, attempt, conclusion, and server-side run state.
- Create or update one deterministic GitHub Issue per source run, close it
  after successful recovery, and mark superseded or exhausted runs clearly.
- Retry eligible import mismatches and Daily Research failures with bounded
  attempts and delays; never retry cancelled, untrusted, permanent, stale-SHA,
  or already-changing runs.
- Make all Daily Research and import recovery artifacts immutable and isolated
  by `github.run_attempt`.
- Add characterization, policy, controller, CLI, workflow, artifact-flow, and
  fail-closed regression tests.
- Run focused, lint, type, diff, Fast, Full, and independent-review gates;
  commit, push, open a PR, and wait for green CI.
## Allowed Scope
Directly related GitHub workflows, daily/import scripts, safe result contracts,
workflow and controller tests, action pin policy if required, task records,
continuity, and direct callers.
## Prohibited Changes
- Do not hardcode dates, compare freshness to the current calendar date, fake
  freshness, publish misaligned sources, bypass validation, or force success.
- Do not add unbounded retries, retry superseded or non-main code, overwrite
  immutable artifacts, expose logs/secrets/URLs/project refs, or execute
  untrusted workflow artifacts in a privileged recovery context.
- Do not change ranking or decision semantics, supported horizons, market or
  asset isolation, point-in-time rules, historical identity policy,
  `RESEARCH_ONLY`, or `HARD_FAIL`.
- Do not update protected `main` without a separate final authorization after
  this Work Package's PR is green.
## Public Contracts
- Only horizon 5 is supported; all other horizons remain
  `UNSUPPORTED_HORIZON`.
- Rank model remains the sole final ranking source and the frontend computes no
  replacement score.
- Snapshot and decision timestamps come only from the validated published
  snapshot; latest-valid selection remains deterministic and fail closed.
- TWSE/TPEx and ETF/common-stock partitions remain isolated.
- `available_at <= decision_at`, `RESEARCH_ONLY`, `HARD_FAIL`, and historical
  identity policies remain unchanged.
- Recovery may repeat an unchanged validated pipeline attempt; it may not
  change data acceptance or publication semantics.
## Risk Classification
HIGH: the controller receives write permission to rerun production workflows
and create Issues. Incorrect trust checks, deduplication, retry limits, or
artifact generation could cause loops, stale-code execution, evidence loss, or
repeated external writes.
## Validation Plan
- Add focused unit tests for event trust, current-main SHA checks, reason
  classification, retry/exhaustion policy, delays, API state revalidation,
  Issue deduplication/reopen/close, and sanitized reporting.
- Add workflow contract tests for exact triggers, minimal permissions,
  concurrency, action pins, full-rerun endpoint, attempt-qualified artifacts,
  and unchanged fail-closed Production dependencies.
- Run affected import, ingestion, Daily Research, publication, and snapshot
  tests plus relevant frontend tests when shared contracts require them.
- Run Ruff/lint, basedpyright/type checks, action pin validation, actionlint,
  `git diff --check`, and repository quality checks.
- Run `pwsh -File scripts/verify-fast.ps1` and
  `pwsh -File scripts/verify-full.ps1` because shared production workflows and
  artifact contracts are touched.
- Obtain an independent read-only review, push a non-protected feature branch,
  create a PR, and wait for all required CI checks to pass.
## Stop Conditions
- Mark PARTIAL if safe recovery requires unavailable repository settings,
  credentials, or an external notification authority beyond GitHub Issues.
- Mark BLOCKED only after the repository-defined repeated-blocker threshold is
  met and no safe in-scope alternative remains.
- Stop after a green PR and final production evidence, immediately before any
  protected-main update.
## Definition of Done
- Misalignment and eligible Daily Research failures produce one sanitized,
  persistent, deduplicated report.
- Only trusted failures at the current `main` SHA retry, with deterministic
  attempt limits and no recursion; superseded/permanent/cancelled failures do
  not retry.
- Recovery success closes its report; exhaustion remains visible and no
  validation or publication gate is weakened.
- Every workflow attempt uses its own immutable artifact generation and never
  mixes artifacts between attempts.
- Focused, lint, type, actionlint, diff, Fast, Full, and independent review
  pass; a feature branch and PR exist with green CI.
- The Work Package is archived and protected `main` remains unchanged pending
  separate final authorization.
## Results
- In progress.
