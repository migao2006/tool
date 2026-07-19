"""Audit contracts for the TWSE supplemental-history queue."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from .contracts import IngestionError


def _integer(row: Mapping[str, object], name: str) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_RPC_INVALID",
            f"supplemental snapshot is missing {name}",
        )
    return value


@dataclass(frozen=True)
class HistoricalSupplementalBackfillSnapshot:
    task_count: int
    adjusted_bars_remaining: int
    institutional_flows_remaining: int
    margin_short_remaining: int
    succeeded: int
    exhausted: int

    @classmethod
    def from_row(
        cls, row: Mapping[str, object]
    ) -> "HistoricalSupplementalBackfillSnapshot":
        return cls(
            **{
                name: _integer(row, name)
                for name in (
                    "task_count",
                    "adjusted_bars_remaining",
                    "institutional_flows_remaining",
                    "margin_short_remaining",
                    "succeeded",
                    "exhausted",
                )
            }
        )

    @property
    def remaining(self) -> int:
        return (
            self.adjusted_bars_remaining
            + self.institutional_flows_remaining
            + self.margin_short_remaining
        )


@dataclass(frozen=True)
class HistoricalSupplementalBackfillSummary:
    outcome: str
    start_date: str
    end_date: str
    attempted_tasks: int
    succeeded_tasks: int
    retried_tasks: int
    fetched_rows: int
    archived_rows: int
    quarantined_rows: int
    quota_remaining_at_start: int
    request_budget: int
    allowed_datasets: tuple[str, ...]
    remaining_adjusted_bars: int
    remaining_institutional_flows: int
    remaining_margin_short: int
    exhausted_tasks: int
    reason_codes: tuple[str, ...]
    system_status: str = "RESEARCH_ONLY"
    usage_scope: str = "RAW_LANDING_ONLY"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["allowed_datasets"] = list(self.allowed_datasets)
        value["reason_codes"] = list(self.reason_codes)
        return value
