# Extract Archive/Current-Publication Row-Adaptation Boundary

## Status

COMPLETE

## Primary Outcome

Extract and stabilize the archive/current-publication row-adaptation boundary
used by `ArchiveFeatureDatasetBuilder.build` without changing public behavior,
schemas, formal status, or writer ownership.

The completed implementation introduces one market-neutral internal
`ArchiveFeatureRowAdapter` in `archive_feature_rows.py`. The builder now
delegates manifest ordering, archive/current-publication canonicalization,
archive-over-publication selection, provenance binding, hard-fail feature-row
selection, and output-row adaptation to that boundary.

## Repository and Branch

- Repository:
  `C:/Users/a0912/Documents/Codex/2026-07-22/agents-md-tasks-active-task-md`
- Base branch and revision: `main` at
  `a8b1cedb4cdfb96695d2fad42727b1cc6838a8b9`
- Base remote revision: `origin/main` at the same SHA.
- Work branch: `codex/extract-archive-row-adaptation`
- Initial tree: clean, with `tasks/active/TASK.md` in the canonical `NONE`
  state.
- Initial branch creation:
  `git switch -c codex/extract-archive-row-adaptation` (exit 0).
- No clone, worktree, sandbox repository, or repository copy was created.

## Inventory and Responsibility Split

### Builder responsibilities retained

- Manifest and identity snapshot completeness/scope gates.
- Verified historical archive reads.
- Combined source and dataset hash assembly.
- Price/volume feature calculation.
- Audit aggregation.
- Writer initialization supplied by the caller, per-symbol batch writes,
  `finish`, `abort`, and exception ownership.

### Extracted boundary responsibilities

- Deterministic manifest grouping and range ordering.
- Archive-row parse/listing-period eligibility adaptation.
- Archive canonical-row construction.
- Current-publication canonical-row construction.
- Deterministic archive-over-current-publication selection on overlapping
  dates.
- Source provenance and reason-code binding by decision date.
- Feature `HARD_FAIL` exclusion and reason aggregation.
- Final research-only output-row adaptation.

The adapter accepts verified in-memory row evidence only. It performs no
storage access, manifest acquisition, feature calculation, writer operation,
ranking, decision policy, inference, release, or frontend work.

Archive rows remain incrementally adapted immediately after each verified
archive read. This preserves the original failure ordering and avoids changing
the builder into an all-archives-in-memory reader.

## Direct Callers and Compatibility

Confirmed direct/static callers and entry points remained unchanged:

- `TwseArchiveFeatureDatasetBuilder`
- `TpexArchiveFeatureDatasetBuilder`
- `scripts/build_twse_research_feature_dataset.py`
- `scripts/build_tpex_research_feature_dataset.py`
- Shared venue CLI orchestration in
  `scripts/_build_venue_research_feature_dataset.py`
- Existing TWSE-named compatibility imports in
  `src/data/research/twse_archive_feature_rows.py`

No dynamic module loader, plugin registry, or entry-point loader targets the
row module. Workflow-selected venue CLI names and existing import paths remain
compatibility dependencies.

The existing functions `group_manifests`, `canonical_record`,
`publication_canonical_record`, and `output_row` remain at the same module path
and with the same signatures. They are now thin delegations to the single
adapter implementation. No second business implementation remains.

## Files Changed

1. `src/data/research/archive_feature_builder.py`
2. `src/data/research/archive_feature_rows.py`
3. `tests/test_twse_archive_feature_dataset.py`
4. `tests/test_tpex_feature_pipeline.py`
5. `tasks/active/TASK.md`
6. `tasks/completed/2026-07-23-extract-archive-current-publication-row-adaptation-boundary.md`

No conditional support module was needed. Total tracked-file scope is 6,
below the hard limit of 12. Before this report was added, the complete
base-to-worktree diff was 1,279 insertions and 367 deletions, below the
approximately 2,500-line limit.

## Behavioral Equivalence Evidence

The same public-surface characterization suite passed both before and after
the production extraction.

Characterized and preserved:

- Archive and current-publication canonical key order and values.
- Frozen output key/column order, including all price/volume feature columns.
- `horizon=5`, `LABELS_NOT_ASSEMBLED`, `FEATURE_RESEARCH_ONLY`, and
  `RESEARCH_ONLY`.
- Stable archive manifest ordering.
- Stable decision-date output ordering.
- Archive precedence when a publication row overlaps an archive date.
- Publication inclusion for a non-overlapping exact date.
- Archive/publication provenance IDs, object keys, hashes, and reason codes.
- `latest_available_at <= decision_at` under the existing research scheduling
  hint while preserving the later observed timestamp and a failed strict PIT
  audit.
- Current identity remains explicitly unverified historical evidence.
- TWSE/TPEx isolation and common-stock/ETF scope rejection.
- Incomplete manifest snapshot rejection.
- Feature `HARD_FAIL` exclusion and all-hard-fail abort.
- Empty/invalid result behavior, exception reason codes, partial-file cleanup,
  and writer abort behavior.
- Existing TWSE compatibility import identities.

Independent AST comparisons against `main` confirmed exact matches for:

- `ArchiveFeatureDatasetBuilder.__init__`
- `ArchiveFeatureDatasetBuilder.build`
- `SourceProvenance` field order
- Existing top-level row-adapter signatures
- Existing `__all__` exports
- Archive canonical, publication canonical, and output-row dictionary key
  order (18, 18, and 34 base entries respectively).

Writer review confirmed the same two `abort` sites and one each of
`write_rows` and `finish`, in the same fail-closed try/except structure.

## Point-in-Time and Scope Evidence

- Canonical archive and publication rows remain
  `point_in_time_status="UNVERIFIED"`.
- Output remains `point_in_time_audit_pass=False` for the current
  first-observed research path.
- The observed timestamp remains audit-visible; it is not rewritten as
  historical truth.
- The prior formal-promotion audit remains applicable: this boundary produces
  research-only/no-formal-candidate evidence and introduces no promotion path.
- The TPEX manifest contract still rejects TWSE and ETF manifests with
  `TPEX_ARCHIVE_SCOPE_MISMATCH`.
- A TPEX-configured adapter rejects a TWSE identity with
  `TPEX_CURRENT_IDENTITY_SCOPE_MISMATCH`.
- A TWSE builder rejects a TPEX current publication with
  `TWSE_DAILY_PUBLICATION_SCOPE_MISMATCH`.
- `HARD_FAIL` rows are absent from persisted output. When no eligible rows
  remain, the builder raises `TWSE_RESEARCH_FEATURE_ROWS_EMPTY` and aborts the
  writer.

No ranking, horizon, decision policy, frontend scoring, prediction, formal
promotion, or artifact-contract module changed.

## Validation Results

### Focused tests

Required command under the repository-managed environment:

```powershell
& .\.venv\Scripts\Activate.ps1
python -m pytest `
  tests/test_twse_archive_feature_dataset.py `
  tests/test_tpex_feature_pipeline.py `
  tests/test_twse_feature_build_cli.py `
  tests/test_tpex_feature_build_cli.py `
  tests/test_venue_feature_build_cli_contract.py -q
```

- Final exit code: 0
- Result: 18 passed.
- The pre-extraction archive/TPEX characterization subset passed with 11
  tests; the final direct-seam subset passed with 13 tests.

The first bare-system-Python attempt exited 1 before test collection because
that interpreter lacked the repository-configured `pytest-xdist` plugin for
`-n/--maxprocesses`. No test or product failure occurred. The locked
repository environment was then used for every reported passing run.

### Direct lint and type checks

```powershell
uv run --with "ruff==0.15.22" ruff check src/data/research/archive_feature_builder.py src/data/research/archive_feature_rows.py tests/test_twse_archive_feature_dataset.py tests/test_tpex_feature_pipeline.py
```

- Exit code: 0
- Result: all checks passed.

```powershell
uv run --with "basedpyright==1.39.9" basedpyright src/data/research/archive_feature_builder.py src/data/research/archive_feature_rows.py tests/test_twse_archive_feature_dataset.py tests/test_tpex_feature_pipeline.py
```

- Exit code: 0
- Result: 0 errors, 0 warnings, 0 notes.

An informational `ruff format --check` run exited 1 because all four selected
existing files would be reformatted. Ruff formatting is not a configured
repository gate or pre-commit hook; applying a broad restyle was outside this
contract-preserving Work Package. The configured pinned Ruff lint passed.

### Whitespace and repository instructions

- `git diff --check` — exit 0; no whitespace errors.
- `python scripts/check_agents_length.py` — exit 0 via Fast verification:
  root 80/100 lines, 5,127/16 KiB, combined 22,074/28 KiB.

### Fast verification

```powershell
pwsh -File scripts/verify-fast.ps1
```

- Exit code: 0
- Result: 17 instruction tests passed; Fast verification passed.

### Full verification

First run:

- Exit code: 1.
- Result before correction: 991 passed, 1 failed.
- Sole failure:
  `tests/test_codex_workflow_contract.py::test_single_active_task_structure`.
- Root cause: the active task had a blank line between `## Status` and
  `ACTIVE`.
- Bounded correction: removed that one blank line.
- Smallest rerun:
  `uv run --system-certs --extra test pytest -q tests/test_codex_workflow_contract.py::test_single_active_task_structure`
  — exit 0, 1 passed.

Final required command:

```powershell
pwsh -File scripts/verify-full.ps1
```

- Exit code: 0
- Python: 992 passed.
- Frontend dependency step: frozen install, already up to date.
- Playwright discovery: 65 tests in 9 files.
- Playwright execution: 65 passed.
- Result: Full verification passed.

## Independent Review Findings

- Allowed paths only; no prohibited contract, dependency, lockfile, schema,
  migration, workflow, release, prediction, ranking, or frontend file changed.
- No public signature/export or row-key order drift.
- No point-in-time weakening or current-identity historical promotion.
- No TWSE/TPEx or common-stock/ETF mixing.
- No duplicate business implementation.
- No writer lifecycle or exception ownership change.
- No broad ignore, swallowed exception, placeholder, weakened assertion,
  generated output, or untracked file.
- No added secret pattern.
- CRLF conversion warnings are Git working-copy notices; `git diff --check`
  passed.

## Repair Rounds

Repair rounds used: 4 of 5.

1. Calibrated pre-extraction characterization expectations to the confirmed
   existing eligible-window counts and public hard-fail reason.
2. Corrected the direct seam test to compare the complete feature hard-fail
   reason multiset rather than only the injected reason.
3. Added executable runtime type narrowing for two `Mapping[str, object]`
   comparisons found by basedpyright.
4. Corrected the active-task status layout found by the first Full run.

No product behavior was changed to satisfy a test. No assertion was weakened,
test deleted, ignore added, exception swallowed, or point-in-time/scope gate
bypassed.

## Commits, Push, and Draft PR

Substantive commits:

1. `aa09b76564f0bea5bad6f782a3bddf411d341e87`
   `test(data): characterize archive row adaptation`
2. `79513b77c9ec3db0dca653394746ec55719d2992`
   `refactor(data): extract archive row adaptation`

Initial push:

```text
git push -u origin codex/extract-archive-row-adaptation
```

- Exit code: 0.
- Remote branch created and upstream configured.
- After the push, local/remote branch counts were `0 0`.

Draft PR:

- URL: https://github.com/migao2006/tool/pull/97
- Number: 97
- State: OPEN
- Draft: true
- Base: `main`
- Head: `codex/extract-archive-row-adaptation`
- Head at initial creation:
  `79513b77c9ec3db0dca653394746ec55719d2992`

The connected GitHub app listed PRs successfully but its create call returned
403 `Resource not accessible by integration`; no PR was created by that failed
call. The authenticated `gh` fallback then created Draft PR #97 successfully.

The task-record commit containing this report is intentionally not
self-referential; its exact SHA and final follow-up push synchronization are
recorded in the final handoff and visible in Draft PR #97.

## Authorization and Prohibited-Operation Confirmation

Authorization used: `FULL_LOCAL_AND_DRAFT_PR`.

No push to `main`, merge, release, deployment, production/staging access,
migration, database/storage mutation, real Supabase/R2 access, secret
operation, dependency upgrade, lockfile update, force operation, reset,
restore, stash, clean, amend, rebase, clone, worktree, or repository copy
occurred.

## Results

COMPLETE. One market-neutral internal row-adaptation boundary now owns the
natural complete row transformation/selection responsibility, the public
builder delegates to it, compatibility surfaces remain thin and stable, all
required focused/static/Fast/Full gates pass, the substantive commits are
pushed, and Draft PR #97 is open.
