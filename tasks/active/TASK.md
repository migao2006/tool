# Refactor Repository Operating Rules
## Status
ACTIVE
## Authorization
FULL_LOCAL_AND_DRAFT_PR
## Primary Outcome
Refactor the repository's Codex operating instructions into a concise, layered,
internally consistent system that supports complete Work Packages while keeping
production, secrets, protected branches, merge, release, and deployment behind
separate explicit authorization.
## Background
- Root instructions duplicate domain contracts already owned by `.ai/`.
- The current remote-handoff rule requires repeated approval for commits, pushes,
  and pull-request creation instead of treating them as one authorized Work Package.
- `tasks/TASK_TEMPLATE.md` looks active before it contains a real task.
- No concise cross-session continuity file exists.
- Repository tests and CI enforce this instruction architecture, so risk is HIGH.
## Subtasks
1. Inventory current instruction sources, references, and executable checks.
2. Consolidate stable operating policy in root `AGENTS.md`.
3. Normalize active-task, completed-task, and continuity responsibilities.
4. Align directly related Skills, documentation, and workflow contract tests.
5. Run focused, Fast, Full, and independent final review.
6. Archive this task, commit explicitly, push the feature branch, and open a Draft PR.
## Allowed Scope
- `AGENTS.md`, `tasks/**`, `.codex/**`, and directly related `.agents/skills/**`.
- Directly related README, documentation, tests, and non-production validation paths.
- No product implementation code.
## Prohibited Changes
- Product behavior, public APIs, schemas, model or frontend contracts.
- Protected-branch pushes, merge, release, deployment, production workflows or
  resources, destructive migrations, secrets, and real trading operations.
- Unrelated cleanup, broad ignores, weakened tests, or fabricated results.
## Public Contracts
- Existing product, API, schema, data, model, frontend, and Taiwan-market contracts
  remain unchanged; `.ai/product.md`, `.ai/architecture.md`, and `.ai/decisions.md`
  remain authoritative.
- `RESEARCH_ONLY`, point-in-time, market, instrument, ranking, and fail-closed rules
  must not be weakened.
## Risk Classification
HIGH — the changed governance files are executable CI inputs and are enforced by
repository contract tests.
## Validation Plan
- `python scripts/check_agents_length.py`
- `uv run --system-certs --extra test pytest -q tests/test_agents_length.py tests/test_codex_workflow_contract.py`
- Relevant Ruff and basedpyright checks for changed Python tests.
- Internal-link, reference, authority, continuity-size, and placeholder audits.
- `git diff --check`
- `pwsh -File scripts/verify-fast.ps1`
- `pwsh -File scripts/verify-full.ps1`
- Independent full-diff, safety-boundary, secret, and unrelated-change review.
## Stop Conditions
- Conflicting contracts cannot be resolved from repository evidence.
- Required work would weaken a public or safety contract, touch production or
  secrets, require a broader product refactor, or mix unrelated user changes.
- A required external validation dependency cannot be satisfied.
## Definition of Done
- Stable policy, one actual active Work Package, concise continuity, specialized
  rules, and completed records have clear non-overlapping responsibilities.
- Empty templates cannot be executed as tasks; references and automated checks agree.
- Required validation and independent review pass.
- The task is archived, active state returns to `NONE`, changes are committed and
  pushed on `codex/refactor-repository-operating-rules`, and a Draft PR is open.
## Results
IN PROGRESS
