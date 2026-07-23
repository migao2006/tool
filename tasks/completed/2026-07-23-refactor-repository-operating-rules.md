# Refactor Repository Operating Rules
## Status
COMPLETE
## Authorization
FULL_LOCAL_AND_DRAFT_PR
## Primary Outcome
Refactor the repository's Codex operating instructions into a concise, layered,
internally consistent system that supports complete Work Packages while keeping
production, secrets, protected branches, merge, release, and deployment behind
separate explicit authorization.
## Background
- Root `AGENTS.md` mixed stable operating policy with product rules already owned by
  `.ai/` and required repeated approval before pull-request handoff.
- `tasks/TASK_TEMPLATE.md` used status `ACTIVE` while containing placeholders.
- No cross-session continuity file existed.
- `tests/test_codex_workflow_contract.py` and `.github/workflows/project-tests.yml`
  make the instruction architecture executable policy, so the verified risk was HIGH.
## Subtasks
1. Inventory current instruction sources, references, and executable checks.
2. Consolidate stable operating policy in root `AGENTS.md`.
3. Normalize active-task, completed-task, template, and continuity responsibilities.
4. Align directly related Skills, README navigation, and governance contract tests.
5. Run focused, Fast, Full, security, and independent final review.
6. Commit, push the feature branch, create a Draft PR, and archive this task.
## Allowed Scope
- `AGENTS.md`, `tasks/**`, `.codex/**`, directly related `.agents/skills/**`,
  `README.md`, and governance contract tests.
- No product implementation code or executable workflow change.
## Prohibited Changes
- Product behavior, public APIs, schemas, model or frontend contracts.
- Protected-branch pushes, merge, release, deployment, production workflows or
  resources, destructive migrations, secrets, and real trading operations.
- Unrelated cleanup, broad ignores, weakened tests, or fabricated results.
## Public Contracts
- No product, API, schema, data, model, frontend, horizon, ranking, point-in-time,
  venue, instrument, fail-closed, or `RESEARCH_ONLY` contract changed.
- `.ai/product.md`, `.ai/architecture.md`, and `.ai/decisions.md` remain authoritative.
## Risk Classification
HIGH — repository contract tests and PR CI execute against these governance files.
## Validation Plan
- Agent instruction limits and changed Markdown reference audits.
- Focused governance tests plus Ruff and basedpyright for the changed Python test.
- `git diff --check`, Fast verification, mandatory Full verification, staged Gitleaks,
  and independent full-diff/safety-boundary review.
## Stop Conditions
- Conflicting contracts, weakened safety boundaries, broader product work,
  unisolated user changes, protected operations, or unavailable required validation.
## Definition of Done
- Stable, task, continuity, specialized, and historical layers have clear authority.
- Empty templates cannot execute; references and automated contracts agree.
- Required validation passes; changes are committed and pushed on the authorized
  feature branch; a Draft PR is open; active state returns to `NONE`.
## Results
### Instruction inventory and architecture
- Root policy now owns precedence, complete Work Packages, default
  `FULL_LOCAL_AND_DRAFT_PR`, protected operations, evidence/scope discipline,
  layered validation, repair, Git/Draft PR rules, session continuity, stop
  conditions, and completion reporting.
- Product details were removed from root duplication and remain referenced in `.ai/`.
- `tasks/README.md` defines one actual active Work Package, terminal archival, and
  exact `NONE`; `tasks/TASK_TEMPLATE.md` is explicitly non-executable `TEMPLATE`.
- Added `.codex/CONTINUITY.md` as state-only, bounded to 100 lines/12 KiB, with no
  authority or copied task history.
- Existing specialized Skills were preserved. Only implement-feature and
  repository-verification were aligned with the complete Work Package lifecycle.
- README navigation and executable workflow contract tests now cover the new layers.
- CI workflow files and product code were not changed.

### Validation evidence
- `python scripts/check_agents_length.py` — exit 0; root 98/100 lines,
  6,882/16 KiB, combined 24,343/28 KiB across 12 instruction files.
- `uv run --system-certs --extra test pytest -q tests/test_agents_length.py tests/test_codex_workflow_contract.py`
  — exit 0; 27 passed.
- `uv run --system-certs --with "ruff==0.15.22" ruff check tests/test_codex_workflow_contract.py`
  — exit 0.
- `uv run --system-certs --with "basedpyright==1.39.9" basedpyright tests/test_codex_workflow_contract.py`
  — exit 0; 0 errors, 0 warnings, 0 notes.
- Markdown-link, live-reference, authorization-authority, scope, and placeholder
  audits — exit 0; no broken target, obsolete live handoff rule, or extra path.
- `git diff --check` and staged `git diff --cached --check` — exit 0.
- `pwsh -NoProfile -File scripts/verify-fast.ps1` — exit 0.
- `pwsh -NoProfile -File scripts/verify-full.ps1` — exit 0; Fast repeated,
  989 Python tests passed, 65 Playwright tests discovered and passed.
- `gitleaks git --staged --redact --no-banner` with Gitleaks 8.30.1 — exit 0;
  22.95 KB scanned and no leaks found.
- Independent final review — PASS; no unresolved contradiction, broken reference,
  duplicated live authority, safety gap, scope leak, or blocking finding.

### Repair rounds
1. Initial root rewrite measured 129 lines and failed the 100-line contract; wording
   and wrapping were compressed without removing required rules, then the limit passed.
2. One focused test compared the preserved Go/Deno rule across a Markdown line break;
   the assertion was changed to whitespace-normalized semantic matching, then all
   focused tests passed.

### Git and Draft PR
- Branch: `codex/refactor-repository-operating-rules`, based on
  `a8b1cedb4cdfb96695d2fad42727b1cc6838a8b9`.
- Core commit: `1e80fd837e662752682a3480148c778ddbfc572b`
  (`docs(governance): layer repository operating rules`).
- The core commit was pushed to the matching remote branch with 0/0 divergence.
- Draft PR #98: `docs(governance): refactor repository operating rules`
  — https://github.com/migao2006/tool/pull/98
- This terminal record and the canonical active `NONE` state are included in the
  record-only commit following the core commit.
- No push to main, merge, auto-merge, release, deployment, production operation,
  migration, secret operation, remote deletion, or real trading operation occurred.
