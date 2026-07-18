"""Small immutable contracts shared by ingestion modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Mapping


@dataclass(frozen=True)
class ImportSummary:
    as_of_date: date
    requested_as_of_date: date
    dry_run: bool
    fetched_records: Mapping[str, int]
    normalized_records: Mapping[str, int]
    excluded_records: Mapping[str, int]
    database_counts: Mapping[str, int] = field(default_factory=dict)
    source_versions: Mapping[str, str] = field(default_factory=dict)
    source_dates: Mapping[str, str] = field(default_factory=dict)
    system_status: str = "RESEARCH_ONLY"
    reason_codes: tuple[str, ...] = (
        "CORPORATE_ACTIONS_NOT_IMPORTED",
        "SECURITY_HISTORY_NOT_IMPORTED",
    )
    status: str = "PASS"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["as_of_date"] = self.as_of_date.isoformat()
        payload["requested_as_of_date"] = self.requested_as_of_date.isoformat()
        return payload


class IngestionError(RuntimeError):
    """Stable ingestion error that never embeds credentials or row payloads."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
