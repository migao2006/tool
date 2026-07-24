# Add one safe manual full-update workflow
## Status
COMPLETE
## Authorization
`FULL_AUTONOMY_UNTIL_MAIN_UPDATE`
## Primary Outcome
Add one owner-triggered GitHub Actions entry point that safely performs the
complete market import and research update path with automatic aligned-date
resolution, Production publication by default, deterministic no-op behavior,
and an auditable final summary.
## Background
- Authoritative base is `main` commit
  `e0bcf074aed92d14dc52e003cd2ea701efd2c2ab`.
- `import-market-data.yml` and `daily-research-model.yml` already expose
  separate `workflow_dispatch` entry points.
- Successful scheduled import triggers Daily Research, with weekday schedules
  at 19:45 and 21:15 Asia/Taipei, but a manual operator currently must
  coordinate two workflows.
- Bounded recovery, persistent Issue reporting, aligned-date resolution,
  missing-market determination, Staging/Production publication, and final
  verification already exist and must be reused rather than duplicated.
## Subtasks
- Characterize existing dispatch inputs, outputs/artifacts, concurrency groups,
  trust boundaries, resolver behavior, publication gates, and safe no-op paths.
- Add `.github/workflows/manual-full-update.yml` with only
  `workflow_dispatch`, safe defaults, optional validated date, coordinated
  concurrency, and one-button full orchestration.
- Reuse existing import and Daily Research workflow/scripts/contracts without
  duplicating ranking, resolver, retry, validation, or publication logic.
- Produce a GitHub job summary with trigger identity, both source dates,
  aligned date, required markets, Production change, final Production date,
  prediction/gate completeness, and failure/no-op reason.
- Add workflow contract and directly related pipeline/integration tests,
  fixtures, documentation, task state, and continuity.
- Run focused tests, actionlint, Ruff, basedpyright, `git diff --check`, Fast,
  Full, and independent review.
- Commit, push `codex/manual-full-update`, open/update a PR, and repair CI until
  merge-ready; stop before protected `main`.
## Allowed Scope
Directly related GitHub workflows, reusable orchestration/reporting scripts,
workflow/pipeline tests and fixtures, workflow documentation, task records,
continuity, and direct callers.
## Prohibited Changes
- Do not force today's date, fabricate freshness, publish misaligned markets,
  bypass validation, duplicate model/ranking/publication logic, or weaken
  existing recovery and persistent reporting.
- Do not introduce unbounded reruns, unsafe nested workflow privilege,
  artifact collisions, or concurrency that can overlap mutating daily paths.
- Do not change ranking, decision, horizon, venue/asset, point-in-time,
  historical identity, `RESEARCH_ONLY`, or `HARD_FAIL` semantics.
- Do not update protected `main` without one final explicit authorization after
  a green PR.
## Public Contracts
- Horizon 5 remains the only official horizon; all other values remain
  `UNSUPPORTED_HORIZON`.
- The ranking model remains the sole final ranking source.
- Snapshot and decision timestamps come only from validated published data.
- TWSE/TPEx and ETF/common-stock partitions remain isolated.
- `available_at <= decision_at`, no look-ahead/survivorship bias,
  `RESEARCH_ONLY`, `HARD_FAIL`, and no-placeholder policies remain unchanged.
- A valid no-op is successful only when existing contracts prove no market
  requires publication and its summary explains that result.
## Risk Classification
HIGH: this adds a one-button Production-capable workflow coordinating two
mutating pipelines. Incorrect concurrency, input propagation, status handling,
or summaries could duplicate writes, mask partial failure, or publish an
invalid research snapshot.
## Validation Plan
- Add focused workflow contract tests for trigger-only dispatch, defaults,
  optional inputs, permissions, concurrency, workflow reuse, outcome
  propagation, fail-closed behavior, and required summary fields.
- Run affected import, resolver, publication, recovery, and workflow tests.
- Run actionlint on all affected workflows, Ruff on affected Python, and
  basedpyright on affected typed modules.
- Run immutable action-pin/lock checks, task/instruction checks,
  `git diff --check`, and `pwsh -File scripts/verify-fast.ps1`.
- Run `pwsh -File scripts/verify-full.ps1` because Production workflow
  orchestration and shared release paths are affected.
- Obtain an independent read-only final review.
- Push the feature branch, create/update the PR, and wait for every selected CI
  and Vercel check to pass.
## Stop Conditions
- Mark PARTIAL if GitHub cannot safely compose the existing workflows without a
  minimum reusable seam that preserves current recovery and concurrency.
- Mark BLOCKED only after the repository-defined repeated-blocker threshold
  when required external GitHub permissions or validation are unavailable.
- Stop immediately before any protected-main update.
## Definition of Done
- One manual workflow starts the complete safe update path with defaults
  `dry_run=false`, `publish_production=true`, and blank `as_of_date`.
- The workflow reuses existing import and Daily Research contracts, cannot
  overlap unsafe scheduled/manual publication, validates any supplied date,
  succeeds with a clear no-op reason, and always writes the required summary.
- Existing recovery/reporting and all public contracts remain intact.
- Focused, lint/type, actionlint, diff, Fast, Full, and independent review pass.
- Task/continuity are terminal, branch is committed and pushed, PR is green and
  merge-ready, and protected `main` remains unchanged.
## Results
- Added dispatch-only `manual-full-update.yml` with Production-safe defaults,
  main/date preflight, sequential reusable Import and Daily calls, distinct
  caller concurrency, and an always-run fail-closed summary.
- Added only the minimum `workflow_call` seams to the existing Import and Daily
  workflows. Import retains current-source semantics; optional `as_of_date`
  applies only to the existing Daily resolver and its point-in-time gates.
- Resolver output now preserves the already-validated Production snapshot
  counts needed to prove no-op completeness without another database query.
- Added a strict summary contract that composes attempt-qualified Import,
  resolver, and Production-verifier artifacts; it rejects missing, extra,
  wrong-market/date/environment, incomplete prediction, and gate-count
  evidence.
- Extended existing bounded recovery to the Manual wrapper. A final Production
  verifier connection failure now receives the existing bounded rerun only
  from an exact two-file artifact; malformed, permanent, mixed, or extra-file
  evidence remains report-only.
- Added operator documentation and regression coverage for defaults, dry-run,
  Staging-only, one/two-market publication, no-op, historical target below the
  current aligned date, recovery, trust boundaries, and summary sanitization.
- Focused affected suite passed: 112 tests.
- Ruff passed; basedpyright reported 0 errors and 0 warnings; affected
  actionlint and `git diff --check` passed.
- Complete quality/security verification passed, including 175 immutable
  Action references, 32 exact Python locks, 37 migrations, Deno 47 tests,
  Gitleaks, pip-audit, CSP, and release evidence.
- Fast verification passed. Full verification passed with 1,114 Python tests
  and 66 Playwright tests.
- Independent final read-only review reported zero BLOCKER, HIGH, MEDIUM, or
  LOW findings.
- Implementation commit `eaceb9d24881f01948c427fb214ad4a87ff55021`
  was pushed to `codex/manual-full-update`; Draft PR #102 targets `main`.
- All first-head GitHub Actions and Vercel checks passed. This archive and
  continuity update form the terminal record commit; its checks must also pass
  before the PR is marked ready.
- No Production-capable Manual run was triggered from the feature branch
  because the workflow is intentionally restricted to `main`.
- Protected `main` remains at
  `e0bcf074aed92d14dc52e003cd2ea701efd2c2ab`.
