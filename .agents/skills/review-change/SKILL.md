---
name: review-change
description: Perform a read-only review of current repository changes for correctness, financial-data integrity, security, compatibility, and test gaps; do not modify the working tree.
---

# Review Change

- Remain read-only and do not modify files, configuration, or Git state.
- Read the active task, relevant contracts, and the complete scoped diff.
- Prioritize functional correctness, point-in-time integrity, data leakage, security, API/schema compatibility, error handling, test gaps, and unnecessary changes.
- Order findings by severity and include a file path plus useful location for every confirmed issue.
- Label each item `Confirmed defect`, `Risk`, or `Suggestion`; do not present speculation as fact.
- State explicitly when no confirmed issue is found and note any validation not performed.
