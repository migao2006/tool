# Complete Archive Row-Adaptation Refresh

## Status

COMPLETE

## Authorization

FULL_AUTONOMY_UNTIL_MAIN_UPDATE

The Work Package was authorized to reconcile and modify the existing
`codex/extract-archive-row-adaptation` branch, validate it, push it, update PR
#97, and repair directly related failures. Updating `main` or another protected
branch remained outside this authorization.

## Primary Outcome

Refresh PR #97 against current `origin/main` and complete the
archive/current-publication row-adaptation extraction so
`ArchiveFeatureDatasetBuilder.build` delegates deterministic source selection
and row adaptation to one market-neutral boundary without observable contract,
point-in-time, provenance, audit, hash, exception, or writer-lifecycle drift.

## Repository and Reconciliation

- Repository:
  `C:/Users/a0912/Documents/Codex/2026-07-22/agents-md-tasks-active-task-md`
- Authoritative base: `origin/main` at
  `88fef120648adff8023aff3696ce2df042463ede`.
- Existing branch: `codex/extract-archive-row-adaptation`.
- Pre-refresh branch head:
  `06356f03b2d7106d501d377054ae0cceb8c78821`.
- Current main was merged normally without conflict or force operation.
- Refresh merge:
  `04f4879757826495f1a632a98f5d5c1657825ac6`.
- Regression-evidence commit:
  `70ba305eb55249e64324b388c92014005e4828aa`.
- The product implementation files were byte-identical before and after the
  main merge; main introduced governance records only.

## Responsibility Boundary

### Builder responsibilities retained

- Manifest and identity completeness/scope validation.
- Verified historical archive reads.
- Source and dataset hash assembly.
- Price/volume feature calculation.
- Audit aggregation and publication counters.
- Writer `write_rows`, `finish`, `abort`, and exception ownership.

### Market-neutral adapter responsibilities

- Deterministic manifest grouping and date-range ordering.
- Archive and current-publication canonical-row adaptation.
- Incremental archive-row accumulation via `previous=`.
- Archive-over-publication precedence.
- Provenance and source reason binding by decision date.
- Feature HARD_FAIL exclusion and reason aggregation.
- Research-only output-row adaptation.

Existing top-level row functions are thin delegations. No second row-selection
or row-adaptation business implementation remains.

## Scope and Changes

The original PR implementation remains the production implementation:

- `src/data/research/archive_feature_builder.py`
- `src/data/research/archive_feature_rows.py`

This refresh added direct regression evidence in:

- `tests/test_twse_archive_feature_dataset.py`

The added tests cover:

- Duplicate dates inside one archive source.
- Duplicate dates across incrementally supplied archive sources.
- Exact-once source, parsed, exclusion, and publication counter accumulation.
- Immutability of previous adapted results.
- Archive precedence over an overlapping publication row.
- Provenance association for records retained from each archive source.
- Duplicate fail-closed reason propagation through feature windows.
- Writer success order: `write_rows` followed by `finish`.
- Writer failure order: `write_rows` followed by `abort`, preserving the
  original exception.

No caller, compatibility wrapper, contract, schema, workflow, dependency,
migration, deployment, ranking, decision, prediction, frontend, or formal
promotion file changed.

## Contract and Behavior Evidence

- AST comparison against `origin/main` passed for
  `ArchiveFeatureDatasetBuilder.__init__`, `build`, all existing public
  top-level row-function signatures, `SourceProvenance` fields, row-module
  `__all__`, and canonical/publication/output dictionary key order.
- Builder writer-call structure remains two `abort` sites and one each of
  `write_rows` and `finish`.
- `archive_feature_contracts.py` and all direct wrapper/CLI callers have zero
  diff from `origin/main`.
- Archive manifests remain deterministically ordered and overlapping campaign
  ranges fail closed.
- Archive rows retain precedence over an overlapping publication row.
- Within-source and cross-source duplicate canonical bars retain the existing
  first-record feature behavior and produce `DUPLICATE_CANONICAL_BAR`; affected
  feature rows cannot be persisted.
- Incremental `previous=` results accumulate source and parsed counts once.
  Previous exclusion counts remain one, not one per incremental call.
- Provenance for non-duplicate persisted rows follows the archive source that
  supplied the selected decision date. Publication overlap does not replace
  archive provenance.
- `latest_available_at <= decision_at` remains true for persisted output while
  the later observed availability remains audit-visible and the strict
  point-in-time audit remains false.
- TWSE/TPEx and COMMON_STOCK/ETF isolation remain fail closed.
- HARD_FAIL and all-hard-fail paths persist no eligible row.
- Output remains `FEATURE_RESEARCH_ONLY` / `RESEARCH_ONLY`; no formal promotion,
  ranking, or product path was introduced.
- Output schemas, column order, artifacts, serialization, hashes, reason codes,
  audit aggregation, exception types, and CLI entry points remain unchanged.

## Validation Results

### Focused tests

Initial post-refresh baseline:

```powershell
uv run --system-certs --extra test pytest `
  tests/test_twse_archive_feature_dataset.py `
  tests/test_tpex_feature_pipeline.py `
  tests/test_twse_feature_build_cli.py `
  tests/test_tpex_feature_build_cli.py `
  tests/test_venue_feature_build_cli_contract.py -q
```

- Exit code: 0
- Result before new tests: 18 passed.
- Final result: 21 passed.

The first bare `python -m pytest` attempt exited 1 before collection because
that interpreter lacked the configured `pytest-xdist` plugin. The repository's
locked `uv` test environment was then used for every reported passing Python
run.

### Lint

```powershell
uv run --with "ruff==0.15.22" ruff check `
  src/data/research/archive_feature_builder.py `
  src/data/research/archive_feature_rows.py `
  tests/test_twse_archive_feature_dataset.py `
  tests/test_tpex_feature_pipeline.py
```

- Exit code: 0
- Result: all checks passed.

### Type checks

```powershell
uv run --with "basedpyright==1.39.9" basedpyright `
  src/data/research/archive_feature_builder.py `
  src/data/research/archive_feature_rows.py
```

- Exit code: 0
- Result: 0 errors, 0 warnings, 0 notes.

### Repository and security checks

- `tests/test_codex_workflow_contract.py`: 11 passed.
- `python scripts/check_agents_length.py`: passed.
- `git diff --check`: passed.
- Gitleaks scan of the complete changed diff: no leaks found.
- Independent AST contract comparison: passed.
- Prohibited-contract and direct-caller diff checks: passed with zero diff.

### Fast verification

```powershell
pwsh -File scripts/verify-fast.ps1
```

- Exit code: 0
- Result: 17 focused instruction tests passed; Fast verification passed.

### Full verification

First run:

- Python: 999 passed.
- Playwright: 64 passed, 1 failed.
- Sole failure: the unrelated iPhone 13 WebKit visual audit reported one
  navigation bounding box at approximately the 3x device pixel scale.
- The failure screenshot showed the expected bottom navigation correctly
  positioned; no frontend file was changed.

Smallest diagnostic rerun:

```powershell
pnpm exec playwright test tests/e2e/mobile-visual-audit.spec.mjs `
  --project=iphone-webkit `
  --grep "iphone-13 四頁與登入抽屜視覺巡檢"
```

- Exit code: 0
- Result: 1 passed.

Final required run:

```powershell
pwsh -File scripts/verify-full.ps1
```

- Exit code: 0
- Python: 999 passed.
- Playwright: 65 passed.
- Result: Full verification passed.

### GitHub checks

For code head `70ba305eb55249e64324b388c92014005e4828aa`:

- Select test scopes: passed.
- Python tests: passed.
- Quality and security: passed.
- Test gate: passed.
- Frontend and browser tests: legitimately skipped by changed-path scope.
- Vercel and Vercel Preview Comments: passed.

## Independent Review

The final review found:

- No public signature, export, schema, key-order, hash, reason-code, or artifact
  drift.
- No duplicate source-selection implementation.
- No point-in-time weakening or current-identity promotion.
- No TWSE/TPEx or COMMON_STOCK/ETF mixing.
- No source/parsed/exclusion counter double-counting.
- No persisted duplicate or HARD_FAIL row.
- No provenance replacement by overlapping publication input.
- No writer lifecycle or exception-ownership change.
- No compatibility import or CLI change.
- No broad ignore, skip, weakened assertion, swallowed exception, placeholder,
  secret, generated tracked output, or unrelated product change.

There is no unresolved material finding.

## Repair Rounds

Three substantive repair rounds were used:

1. The bare Python environment lacked `pytest-xdist`. The root cause was
   environment selection; validation moved to the locked `uv --extra test`
   environment without repository changes.
2. A new test assumed a duplicate reason would be counted once. Current feature
   windows correctly propagate the fail-closed reason to affected rows. The
   test scenario and exact expectation were corrected to characterize existing
   behavior while also exercising provenance from both sources.
3. One WebKit visual-audit measurement failed transiently at device-pixel
   scale. The screenshot and context were inspected, the exact test passed
   alone, and the unchanged final Full suite passed all 65 Playwright tests.

No product behavior, quality gate, assertion strength, point-in-time rule, or
scope check was weakened.

## Git and Pull Request

- Branch: `codex/extract-archive-row-adaptation`.
- Existing PR: https://github.com/migao2006/tool/pull/97
- PR state after the code/evidence push: OPEN, non-Draft, base `main`, head the
  existing feature branch, and mergeable.
- No review, change request, inline comment, or unresolved review thread exists.
- The terminal record commit containing this report follows the verified code
  head and is records-only. Its exact SHA and final current-head CI result are
  recorded in the final handoff and PR state.

## Rollback

Before merge, rollback is simply to leave PR #97 unmerged or close it; main is
unchanged. If a later authorized merge must be reversed, create a dedicated
revert branch from the then-current main, `git revert` the PR merge/squash
commit, rerun the same focused/Fast/Full gates, and merge the revert through a
separate protected-branch authorization. Do not reset or force-push.

## Prohibited-Operation Confirmation

No protected branch update, merge, auto-merge, force-push, release, production
workflow, migration, production-resource change, secret access/output, or
remote branch deletion occurred. The Vercel Git integration created its normal
PR preview status; no manual deployment or production action was performed.

## Results

COMPLETE. PR #97 now contains current main, the original market-neutral
row-adaptation extraction, stronger duplicate/incremental/provenance/writer
regression evidence, successful local Focused/Fast/Full validation, successful
code-head CI, and no unresolved material review finding. The Work Package stops
before updating `main`.
