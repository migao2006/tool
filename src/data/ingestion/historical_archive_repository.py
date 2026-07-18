"""Persist compact R2 object manifests without storing archived rows in Postgres."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, final


class ArchiveManifestWriter(Protocol):
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


@final
class HistoricalArchiveRepository:
    """Write one idempotent manifest after the corresponding R2 object is verified."""

    def __init__(self, writer: ArchiveManifestWriter) -> None:
        self.writer = writer

    def save(self, manifest: Mapping[str, object]) -> None:
        returned = self.writer.upsert(
            "historical_archive_objects",
            [manifest],
            on_conflict="archive_key",
            preserve_existing=True,
        )
        if returned:
            raise AssertionError("manifest upsert should not request returned rows")
