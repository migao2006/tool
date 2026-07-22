---
name: ci-triage
description: Diagnose a failing CI workflow from preserved logs and exact commands; do not use to rerun blindly, weaken gates, or change production deployment settings without a confirmed cause.
---

# CI Triage

1. Preserve the workflow, job, step, log excerpt, and exact failing command.
2. Identify the first real failure rather than downstream cancellation or gate failures.
3. Classify it as code, test, configuration, secret/permission, runner/environment, or external-service failure.
4. Reproduce locally when safe and isolate the smallest confirmed cause.
5. Propose or apply only the scoped fix authorized by the active task, then rerun the failed command and relevant gate.

Rerunning is not a fix. Never expose secret values, add `continue-on-error` to required checks, or alter production deployment settings before confirming root cause.
