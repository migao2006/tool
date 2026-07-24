# Repair Manual Full Update Production Artifact Handoff
## Status
COMPLETE
## Authorization
`FULL_AUTONOMY_UNTIL_MAIN_UPDATE`, explicitly granted by the user. No protected
branch was updated.
## Primary Outcome
Repair the `Manual full update` workflow so final verification obtains the
required TWSE and TPEx Production artifacts and produces a truthful successful
summary.
## Background
The latest manual full update reached final verification but attempted to download
`daily-research-production-{TWSE,TPEX}-<run>-1` artifacts that its invocation
contractually did not produce.
## Subtasks
- Reproduce the failure from current `main` and locate the first failing boundary.
- Trace upload/download actions, reusable workflow boundaries, run identifiers,
  attempts, artifact names, and cross-workflow access assumptions.
- Implement the smallest safe fix and regression tests without weakening checks.
- Update directly affected documentation and repository state records.
- Run focused, lint/type, Fast, Full, and independent review validation.
- Commit, push the feature branch, create a Pull Request, and verify CI.
## Allowed Scope
`.github/workflows/**`, workflow-related scripts and helpers, directly affected
tests and documentation, and task/continuity records.
## Prohibited Changes
Do not change prediction models, ranking, horizon behavior, temporal contracts,
research/fail-closed semantics, venue isolation, publication contracts, API or
database schemas. Do not update a protected branch without further authorization.
## Public Contracts
Preserve horizon 5, fail-closed Production validation, manual dispatch behavior,
automatic aligned-date resolution without calendar substitution, deterministic
artifacts, and all existing workflow inputs/outputs unless compatibility is kept.
## Risk Classification
HIGH: this changes a Production workflow handoff and final verification path, but
does not alter model, data, publication, or validation semantics.
## Validation Plan
Run focused manual-workflow and artifact regression tests, actionlint, Ruff,
basedpyright, `git diff --check`, repository instruction checks, Fast verification,
Full verification, and an independent final review. Verify the Pull Request CI.
## Stop Conditions
Stop only before a protected-branch update, if a GitHub platform limitation blocks
completion, or if an unrelated subsystem must change.
## Definition of Done
The workflow uses a supported artifact handoff, final verification downloads exact
Production artifacts, summary remains fail-closed, regressions cover the failure,
all required checks pass, and a CI-green Pull Request is ready without updating
`main`.
## Results
- Reproduced the reported errors in main run `30061633611` at SHA
  `47eceb1d7de5f42e0bd70668a3d025fcc4bf24c4`: the run requested
  `dry_run=true` and `publish_production=false`, so Production jobs and artifacts
  were correctly absent, while both final download steps still ran and emitted
  `Artifact not found`.
- Confirmed reusable workflow artifacts share the caller run. Import and resolution
  artifacts used caller run ID `30061633611`, attempt `1`, and exact expected names.
  Artifact isolation, run ID, attempt, and producer naming were not the cause.
- Added reusable outputs for `should_run`, `markets`, and `production_requested`.
  The wrapper now downloads only Production artifacts contractually required for
  the invocation and still attempts/fails closed when a required artifact is absent.
- Added artifact lifecycle regression tests and updated the operator documentation.
- Focused workflow/recovery/summary tests: 95 passed. TDD characterization first
  failed in the two expected assertions, then passed after the repair.
- Pinned quality/security gate passed, including Ruff, basedpyright
  (0 errors, 0 warnings), actionlint, Deno (47 passed), secret scan, and dependency
  audit.
- Fast verification passed. Full verification passed with 1,115 Python and 66
  Playwright tests. Two unrelated one-off browser failures each passed an exact
  rerun before the final clean Full run.
- Independent read-only review reported zero findings and made no changes.
- Implementation commits `6e7c85b` and `2e7d4af` were pushed to
  `codex/repair-manual-update-artifacts`.
- Draft PR #103 was created. CI run `30063441859` passed Select test scopes,
  Python tests, Frontend and browser tests, Quality and security, Test gate, Vercel,
  and Vercel Preview Comments.
- No migration or deployment was required. No protected branch was updated.
