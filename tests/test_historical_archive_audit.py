from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import final

from src.data.archive.contracts import HistoricalArchiveReadError
from src.quality.historical_archive_audit import audit_historical_archive


@dataclass(frozen=True)
class Inspection:
    content_sha256: str
    byte_size: int
    row_count: int
    schema_version: str = "historical_daily_bars.v1"


@final
class RecordingReader:
    def __init__(self, inspections: Mapping[str, Inspection | Exception]) -> None:
        self.inspections = inspections
        self.calls: list[str] = []

    def read(self, manifest: Mapping[str, object]) -> Inspection:
        object_key = str(manifest["object_key"])
        self.calls.append(object_key)
        result = self.inspections[object_key]
        if isinstance(result, Exception):
            raise result
        return result


def _manifest(
    object_key: str,
    *,
    digest: str = "a" * 64,
    byte_size: int = 100,
    row_count: int = 10,
    parsed_row_count: int = 9,
    quarantined_row_count: int = 1,
    bucket_name: str = "alpha-lens-archive",
) -> dict[str, object]:
    return {
        "archive_key": sha256(
            f"{bucket_name}\0{object_key}".encode("utf-8")
        ).hexdigest(),
        "bucket_name": bucket_name,
        "object_key": object_key,
        "parquet_sha256": digest,
        "byte_size": byte_size,
        "row_count": row_count,
        "parsed_row_count": parsed_row_count,
        "quarantined_row_count": quarantined_row_count,
        "schema_version": "historical_daily_bars.v1",
        "source_dataset": "daily_bars",
    }


def test_matching_manifests_and_objects_pass_with_aggregate_counts() -> None:
    first = _manifest("history/2330.parquet")
    second = _manifest(
        "history/2317.parquet",
        digest="b" * 64,
        byte_size=150,
        row_count=12,
        parsed_row_count=12,
        quarantined_row_count=0,
    )
    reader = RecordingReader(
        {
            "history/2330.parquet": Inspection("a" * 64, 100, 10),
            "history/2317.parquet": Inspection("b" * 64, 150, 12),
        }
    )

    result = audit_historical_archive([first, second], reader=reader)

    assert result.passed is True
    assert result.status == "PASS"
    assert result.object_count == 2
    assert result.row_count == 22
    assert result.byte_count == 250
    assert result.reason_codes == ()


def test_duplicate_archive_and_object_keys_fail_closed() -> None:
    manifest = _manifest("history/2330.parquet")
    reader = RecordingReader({"history/2330.parquet": Inspection("a" * 64, 100, 10)})

    result = audit_historical_archive([manifest, dict(manifest)], reader=reader)

    assert result.status == "FAIL"
    assert "HISTORICAL_ARCHIVE_DUPLICATE_ARCHIVE_KEY" in result.reason_codes
    assert "HISTORICAL_ARCHIVE_DUPLICATE_OBJECT_KEY" in result.reason_codes


def test_invalid_manifest_counts_fail_without_reading_object() -> None:
    manifest = _manifest(
        "history/2330.parquet",
        row_count=10,
        parsed_row_count=10,
        quarantined_row_count=1,
    )
    reader = RecordingReader({})

    result = audit_historical_archive([manifest], reader=reader)

    assert result.passed is False
    assert "HISTORICAL_ARCHIVE_MANIFEST_COUNTS_MISMATCH" in result.reason_codes
    assert reader.calls == []


def test_all_reader_integrity_mismatches_are_reported() -> None:
    manifest = _manifest("history/2330.parquet")
    reader = RecordingReader(
        {
            "history/2330.parquet": Inspection(
                "b" * 64,
                101,
                11,
                "historical_daily_bars.v2",
            )
        }
    )

    result = audit_historical_archive([manifest], reader=reader)

    assert result.reason_codes == (
        "HISTORICAL_ARCHIVE_CHECKSUM_MISMATCH",
        "HISTORICAL_ARCHIVE_BYTE_SIZE_MISMATCH",
        "HISTORICAL_ARCHIVE_ROW_COUNT_MISMATCH",
        "HISTORICAL_ARCHIVE_SCHEMA_MISMATCH",
    )


def test_reader_error_and_empty_manifest_fail_closed() -> None:
    manifest = _manifest("history/2330.parquet")
    reader = RecordingReader({"history/2330.parquet": OSError("R2 is unavailable")})

    failed_read = audit_historical_archive([manifest], reader=reader)
    empty = audit_historical_archive([], reader=RecordingReader({}))

    assert failed_read.status == "FAIL"
    assert failed_read.reason_codes == ("HISTORICAL_ARCHIVE_OBJECT_READ_FAILED",)
    assert empty.status == "FAIL"
    assert empty.object_count == empty.row_count == empty.byte_count == 0
    assert empty.reason_codes == ("HISTORICAL_ARCHIVE_MANIFEST_EMPTY",)


def test_reader_preserves_stable_archive_failure_reason() -> None:
    manifest = _manifest("history/2330.parquet")
    reader = RecordingReader(
        {
            "history/2330.parquet": HistoricalArchiveReadError(
                "HISTORICAL_ARCHIVE_CONTENT_MISMATCH",
                "payload mismatch",
            )
        }
    )

    result = audit_historical_archive([manifest], reader=reader)

    assert result.status == "FAIL"
    assert result.reason_codes == ("HISTORICAL_ARCHIVE_CONTENT_MISMATCH",)
