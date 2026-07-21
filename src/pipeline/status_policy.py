"""Fail-closed publication status policy for pipeline results."""

from __future__ import annotations

from dataclasses import replace

from .contracts import PipelineResult, PipelineStatus


_STATUS_SEVERITY = {
    PipelineStatus.PASS: 0,
    PipelineStatus.RESEARCH_ONLY: 1,
    PipelineStatus.FAIL: 2,
}


def enforce_configured_status_cap(
    result: PipelineResult,
    configured_status: str,
) -> PipelineResult:
    """Prevent a runner from publishing above the reviewed configuration status."""

    status_cap = PipelineStatus(configured_status)
    if _STATUS_SEVERITY[result.status] >= _STATUS_SEVERITY[status_cap]:
        return result

    reason = f"CONFIG_STATUS_{status_cap.value}"
    reason_codes = tuple(dict.fromkeys((reason, *result.reason_codes)))
    return replace(result, status=status_cap, reason_codes=reason_codes)
