---
name: fix-bug
description: Reproduce and fix a confirmed repository defect with regression coverage; do not use when only analysis or speculative hardening was requested.
---

# Fix Bug

1. Reproduce the defect first and preserve the command, output, logs, or failing test.
2. Trace the root cause; label hypotheses until evidence confirms them.
3. Add a regression test that fails for the confirmed defect.
4. Apply the smallest valid fix without changing unrelated behavior.
5. Confirm the regression test changes from failing to passing, then run affected tests and fast verification.
6. Inspect the diff and report root cause, validation, risk, and rollback.

Never swallow errors, weaken assertions, delete tests, hide failures, or use retries as the claimed fix.
