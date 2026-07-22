---
name: implement-feature
description: Implement a scoped repository feature after its outcome and contracts are defined; do not use for diagnosis-only requests, broad cleanup, or production operations.
---

# Implement Feature

1. Read `tasks/active/TASK.md` and the relevant product and architecture contracts.
2. Find the smallest valid implementation boundary and confirm API, schema, model, and UI contracts.
3. Plan before editing; preserve unrelated changes and product invariants.
4. Add or update tests with the implementation.
5. Run focused tests, then `pwsh -File scripts/verify-fast.ps1`.
6. Inspect the full diff and request an independent read-only review when delegation is explicitly allowed.
7. Run full verification when the change crosses modules, alters contracts, or raises regression risk.
8. Report residual risks, compatibility impact, and rollback steps.
