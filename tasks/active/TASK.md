# Extract Archive/Current-Publication Row-Adaptation Boundary

## Status

ACTIVE

## Primary Outcome

Extract and stabilize the archive/current-publication row-adaptation boundary
currently embedded in or directly supporting
`ArchiveFeatureDatasetBuilder.build`. The builder must delegate row
canonicalization, current-publication adaptation, deterministic source-row
selection, and output-row adaptation to one market-neutral internal boundary
without changing externally observable behavior.

## Confirmed Context

- The authorized branch is `codex/extract-archive-row-adaptation`, created from
  synchronized `main` at
  `a8b1cedb4cdfb96695d2fad42727b1cc6838a8b9`.
- The initial working tree was clean and this file was in the standard
  `Status: NONE` state.
- The work is a structural extraction only. It does not authorize formal
  promotion or new product policy.
- Public contracts and fail-closed behavior must be characterized before the
  controlled entry point is changed.

## Subtasks

1. Inventory row-adaptation responsibilities, direct static callers,
   compatibility imports, writer lifecycle, ordering, deduplication,
   provenance, and audit assembly.
2. Add behavior-level characterization tests through existing builder and
   adapter surfaces for archive and current-publication rows.
3. Extract one pure, market-neutral row-adaptation boundary.
4. Make `ArchiveFeatureDatasetBuilder.build` delegate to the boundary while
   retaining thin compatibility adapters where required.
5. Add direct seam tests for equivalence, deterministic selection and ordering,
   provenance, point-in-time rejection, venue and instrument isolation,
   `HARD_FAIL`, incomplete scope, research-only status, and import
   compatibility.
6. Run focused, lint/type, Fast, and Full verification and independently review
   the final diff and contracts.
7. Archive this task, restore the active task to `Status: NONE`, commit explicit
   paths, push the authorized branch, and create or update a Draft PR.

## Allowed Scope

- `src/data/research/archive_feature_builder.py`
- `src/data/research/archive_feature_rows.py`
- `src/data/research/twse_archive_feature_rows.py`
- `tests/test_twse_archive_feature_dataset.py`
- `tests/test_tpex_feature_pipeline.py`
- `tests/test_venue_feature_build_cli_contract.py`
- `tasks/active/TASK.md`
- `tasks/completed/2026-07-23-extract-archive-current-publication-row-adaptation-boundary.md`
- Conditionally, only when directly required:
  - `src/data/research/__init__.py`
  - one new market-neutral internal row-adaptation module under
    `src/data/research/`
  - `tests/test_twse_feature_build_cli.py`
  - `tests/test_tpex_feature_build_cli.py`
- Read-only inspection elsewhere in the repository.
- Directly related low-risk fixes in this same data flow only when they block
  the outcome, preserve public contracts, and receive regression coverage or
  static validation.

## Prohibited Changes

- Do not modify `src/data/research/archive_feature_contracts.py`.
- Do not change public artifact or persisted-data schemas, daily-bar
  publication or ingestion, venue inference, model restoration, ranking,
  decision policy, prediction, frontend, Supabase, R2, release manifest, or
  workflow behavior.
- Do not change dependencies, lockfiles, migrations, production or staging
  resources, formal-promotion status, horizon behavior, scoring behavior, or
  unrelated code.
- Do not merge TWSE with TPEx or ETF with ordinary/common-stock flows.
- Do not introduce a second ranking source, frontend final score, look-ahead
  bias, survivorship bias, fake results, guaranteed profit, or precise future
  price claims.

## Public Contracts

- `ArchiveFeatureDatasetBuilder.build`
- `ArchiveFeatureAudit`
- `ArchiveFeatureBuildError`
- Existing canonical-row, current-publication, and output-row adapter
  signatures
- Existing TWSE and TPEx builder wrapper imports
- Existing TWSE-named row-module imports
- Output columns and column order
- Artifact schema, artifact names, serialization behavior, and deterministic
  hashes
- Provenance and audit fields and aggregation semantics
- Reason codes
- CLI arguments and exit behavior
- Writer initialization, commit, abort, cleanup, exceptions, and fail-closed
  behavior
- Formal support remains `horizon=5`; other horizons remain
  `UNSUPPORTED_HORIZON`.
- `available_at <= decision_at` remains enforced.
- `HARD_FAIL` cannot produce formal candidates or formal output.
- Output remains explicitly `RESEARCH_ONLY`.

## Validation Plan

- Smallest affected tests during characterization and extraction.
- Focused suite:

  `python -m pytest tests/test_twse_archive_feature_dataset.py tests/test_tpex_feature_pipeline.py tests/test_twse_feature_build_cli.py tests/test_tpex_feature_build_cli.py tests/test_venue_feature_build_cli_contract.py -q`

- Directly related repository-established lint and type checks.
- `python scripts/check_agents_length.py`
- `git diff --check`
- `pwsh -File scripts/verify-fast.ps1`
- `pwsh -File scripts/verify-full.ps1`
- Final review:
  - `git status --short --branch`
  - `git diff --name-status`
  - `git diff --stat`
  - `git diff`

## Authorization

`FULL_LOCAL_AND_DRAFT_PR` for this Work Package: local inspection and edits,
tests and directly related fixes, task archival, explicit-path commits, push to
`codex/extract-archive-row-adaptation`, and Draft PR creation or update. No
merge, release, deployment, production/staging access, migration, secret
operation, or push to `main` is authorized.

## Repair Policy

- Maximum repair rounds: 5.
- Maximum attempts for the same root cause: 3.
- Each round identifies the first concrete failure, determines the root cause,
  applies one bounded correction, and reruns the smallest affected check.
- Do not weaken gates or assertions, delete tests, add broad ignores, swallow
  exceptions, insert placeholders, bypass point-in-time/scope checks, or change
  expected output without contract evidence.

## Stop Conditions

Stop as `BLOCKED` or `PARTIAL` only if a public API/schema/reason/formal-status
decision must change; point-in-time equivalence cannot be established; current
identity can enter a formal path; callers cannot be retained with thin
adapters; more than 12 tracked files or an unreviewable approximately
2,500-line diff is required; a second major subsystem, core dependency,
migration, production resource, secret, deployment, or real external-service
write is required; user changes cannot be separated; a major security,
data-leak, look-ahead, or survivorship-bias defect is discovered; five repair
rounds are exhausted; or old/new behavior differs materially without
explanation.

## Definition of Done

- One market-neutral row-adaptation boundary owns the complete extracted
  responsibility and the builder delegates to it.
- No duplicated business implementation remains; compatibility adapters are
  thin.
- Characterization and seam tests evidence all practical behavioral
  invariants, and public contracts remain stable.
- Focused tests, direct lint/type checks, `git diff --check`, Fast verification,
  and Full verification pass.
- Independent review finds no unexplained behavior drift, unrelated changes,
  secrets, or scope violation.
- This task is archived with exact evidence; the active task returns to
  `Status: NONE`.
- Explicit-path commits are pushed to the authorized feature branch and a Draft
  PR is created or updated.

## Results

Pending execution.
