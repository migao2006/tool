"""Port and result contracts for the gated research snapshot adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class SupabaseResearchWriter(Protocol):
    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]: ...

    def rpc(
        self,
        function_name: str,
        parameters: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True)
class ResearchSupabasePublishResult:
    prediction_run_id: int
    prediction_count: int
    target_environment: str


__all__ = ["ResearchSupabasePublishResult", "SupabaseResearchWriter"]
