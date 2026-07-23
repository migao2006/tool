# Complete Archive Row-Adaptation Extraction

## Status
ACTIVE

## Authorization

FULL_AUTONOMY_UNTIL_MAIN_UPDATE

The Work Package may inspect, modify, validate, commit, push the existing
`codex/extract-archive-row-adaptation` branch, update PR #97, repair directly
related CI failures, and mark the PR Ready. It must stop immediately before an
operation that updates `main` or another protected branch.

## Primary Outcome

Refresh PR #97 against current `origin/main` and complete the
archive/current-publication row-adaptation extraction so
`ArchiveFeatureDatasetBuilder.build` delegates deterministic source selection
and row adaptation to one market-neutral boundary without observable contract,
point-in-time, provenance, audit, hash, exception, or writer-lifecycle drift.

## Background

- Authoritative base: `origin/main` at
  `88fef120648adff8023aff3696ce2df042463ede`.
- Existing implementation branch:
  `codex/extract-archive-row-adaptation`.
- Pre-refresh implementation head:
  `06356f03b2d7106d501d377054ae0cceb8c78821`.
- PR #97 is open and contains the existing bounded extraction.
- Current main differs by repository-governance changes and is authoritative.

## Subtasks

1. Reconcile the existing branch with current `origin/main` without rewriting
   or duplicating the implementation.
2. Reinspect the complete PR diff, public contracts, direct callers,
   compatibility imports, writer paths, and tests.
3. Confirm the adapter solely owns deterministic manifest/source selection,
   canonical/current-publication adaptation, provenance binding, hard-fail
   output selection, and output-row adaptation.
4. Characterize source precedence, duplicate dates within/across archives,
   incremental `previous=` behavior, counters, provenance, point-in-time gates,
   market/instrument isolation, incomplete scope, HARD_FAIL, RESEARCH_ONLY,
   exception timing, and writer success/abort lifecycle.
5. Make only bounded implementation, test, compatibility, task, and continuity
   corrections required by the same data flow.
6. Run Focused, lint, type, diff, Fast, and mandatory Full verification.
7. Perform an independent final diff and contract review, repair material
   findings, archive this task, commit, push, update PR #97, and confirm
   current-head CI and merge readiness.

## Allowed Scope

- `src/data/research/archive_feature_builder.py`
- `src/data/research/archive_feature_rows.py`
- `tests/test_twse_archive_feature_dataset.py`
- `tests/test_tpex_feature_pipeline.py`
- `tests/test_twse_feature_build_cli.py` when caller-contract evidence requires it
- `tests/test_tpex_feature_build_cli.py` when caller-contract evidence requires it
- `tests/test_venue_feature_build_cli_contract.py` when caller-contract evidence
  requires it
- `tasks/active/TASK.md`
- `tasks/completed/2026-07-23-extract-archive-current-publication-row-adaptation-boundary.md`
- `.codex/CONTINUITY.md`
- A directly required import, type, fixture, or test configuration only when
  repository evidence proves it is necessary for this same outcome.

## Prohibited Changes

- `src/data/research/archive_feature_contracts.py`
- Persisted row or artifact schemas, output column order, artifact names,
  serialization formats, deterministic hashes, or reason-code semantics
- Daily-bar ingestion or publication behavior
- Historical identity or formal-promotion policy
- Ranking, decision, prediction, frontend, horizon, scoring, or formal-status
  behavior
- Dependencies except synchronization required to execute existing validation
- Deployment, migration, production resources, secrets, or unrelated workflows
- A second major subsystem or unrelated cleanup

## Public Contracts

- `ArchiveFeatureDatasetBuilder.build`
- `ArchiveFeatureAudit`
- `ArchiveFeatureBuildError`
- `SourceProvenance`
- Existing public row-adapter signatures and `__all__`
- TWSE/TPEx builder and row-module compatibility imports
- TWSE/TPEx CLI arguments and exit behavior
- Output schemas and column order, artifact names, serialization, and hashes
- Provenance fields, audit aggregation, counters, reason codes, exception types,
  and writer `write_rows`, `finish`, and `abort` behavior
- Official support remains `horizon=5`; other horizons remain
  `UNSUPPORTED_HORIZON`
- TWSE/TPEx and ordinary-equity/ETF flows remain isolated
- `available_at <= decision_at`; no look-ahead or survivorship bias
- HARD_FAIL cannot produce formal candidates or persisted eligible rows
- No fake or placeholder production data
- Output remains RESEARCH_ONLY until formal validation is complete
- No guaranteed-profit or exact-future-price claim

## Risk Classification

HIGH. This is a shared point-in-time and data-contract boundary used by TWSE and
TPEx feature construction.

## Validation Plan

1. Focused venue feature suite:
   `python -m pytest tests/test_twse_archive_feature_dataset.py
   tests/test_tpex_feature_pipeline.py tests/test_twse_feature_build_cli.py
   tests/test_tpex_feature_build_cli.py
   tests/test_venue_feature_build_cli_contract.py -q`
2. Ruff for both changed production modules and their primary tests.
3. basedpyright for both changed production modules.
4. `git diff --check`.
5. `pwsh -File scripts/verify-fast.ps1`.
6. `pwsh -File scripts/verify-full.ps1`.
7. Independent review of the final diff, contracts, secrets, scope, and behavior.
8. Current-head PR checks and thread/review inspection.

Full verification is mandatory. Expensive successful checks are rerun only
after later changes that affect their validated scope.

## Stop Conditions

- The next operation updates `main` or another protected branch.
- Reconciliation requires an unauthorized public API, schema, hash, reason-code,
  or formal-status change.
- Material old/new behavior, point-in-time, provenance, market, instrument,
  HARD_FAIL, exception, or writer-lifecycle equivalence cannot be established.
- More than approximately 10 tracked files or 2,500 changed lines are needed
  without a clearly reviewable justification.
- A second unrelated subsystem, user-change overwrite, production resource,
  secret, migration, or unavailable external decision is required.
- Three materially different attempts at one root cause or five substantive
  Work Package repair rounds are exhausted.

## Definition of Done

- One market-neutral adapter is the only source-selection and row-adaptation
  implementation, and the builder delegates to it.
- The builder retains storage reads, feature calculation, audit aggregation,
  persistence, exception handling, and writer orchestration.
- Public contracts and compatibility imports remain stable.
- Required behavior is covered by executable characterization/regression tests.
- Focused, lint, type, diff, Fast, Full, independent review, and current-head CI
  all pass.
- Task and continuity records are accurate and terminal.
- The existing branch is committed and pushed; PR #97 is updated, Ready, and
  merge-ready.
- No protected branch has been updated.

## Results

In progress.
