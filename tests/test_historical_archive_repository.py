from collections.abc import Mapping, Sequence

from src.data.ingestion.historical_archive_repository import (
    HistoricalArchiveRepository,
)


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "table": table,
                "rows": [dict(row) for row in rows],
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        return []


def test_manifest_repository_is_idempotent_and_never_returns_raw_rows() -> None:
    writer = FakeWriter()
    manifest = {"archive_key": "a" * 64, "row_count": 1}

    HistoricalArchiveRepository(writer).save(manifest)

    assert writer.calls == [
        {
            "table": "historical_archive_objects",
            "rows": [manifest],
            "on_conflict": "archive_key",
            "select": None,
            "return_rows": False,
            "preserve_existing": True,
        }
    ]
