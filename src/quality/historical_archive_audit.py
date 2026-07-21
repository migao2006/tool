"""Fail-closed integrity audit for historical R2 archive manifests."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Protocol

from src.data.archive.contracts import HistoricalArchiveReadError
from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_SCHEMA_VERSIONS,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HistoricalArchiveInspection(Protocol):
    """Integrity fields returned by an injected archive object reader."""

    @property
    def content_sha256(self) -> object: ...

    @property
    def byte_size(self) -> object: ...

    @property
    def row_count(self) -> object: ...

    @property
    def schema_version(self) -> object: ...


class HistoricalArchiveObjectReader(Protocol):
    """Reader boundary; implementations may use R2 and PyArrow internally."""

    def read(
        self,
        manifest: Mapping[str, object],
    ) -> HistoricalArchiveInspection: ...


@dataclass(frozen=True)
class HistoricalArchiveAuditResult:
    """Aggregate manifest and object integrity result."""

    passed: bool
    status: str
    object_count: int
    row_count: int
    byte_count: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class _ManifestRecord:
    raw: Mapping[str, object]
    archive_key: str
    bucket_name: str
    object_key: str
    content_sha256: str
    byte_size: int
    row_count: int
    schema_version: str
    source_dataset: str


def _text(row: Mapping[str, object], field: str) -> str | None:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _integer(row: Mapping[str, object], field: str) -> int | None:
    value = row.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _manifest_record(
    row: Mapping[str, object],
    reasons: list[str],
) -> _ManifestRecord | None:
    archive_key = _text(row, "archive_key")
    bucket_name = _text(row, "bucket_name")
    object_key = _text(row, "object_key")
    content_sha256 = _text(row, "parquet_sha256")
    schema_version = _text(row, "schema_version")
    source_dataset = _text(row, "source_dataset")
    byte_size = _integer(row, "byte_size")
    row_count = _integer(row, "row_count")
    parsed_row_count = _integer(row, "parsed_row_count")
    quarantined_row_count = _integer(row, "quarantined_row_count")

    identity_valid = (
        archive_key is not None
        and _SHA256.fullmatch(archive_key) is not None
        and bucket_name is not None
        and object_key is not None
    )
    if not identity_valid:
        reasons.append("HISTORICAL_ARCHIVE_MANIFEST_IDENTITY_INVALID")

    checksum_valid = (
        content_sha256 is not None and _SHA256.fullmatch(content_sha256) is not None
    )
    if not checksum_valid:
        reasons.append("HISTORICAL_ARCHIVE_MANIFEST_CHECKSUM_INVALID")

    if byte_size is None or byte_size <= 0:
        reasons.append("HISTORICAL_ARCHIVE_MANIFEST_BYTE_COUNT_INVALID")
    if row_count is None or row_count <= 0:
        reasons.append("HISTORICAL_ARCHIVE_MANIFEST_ROW_COUNT_INVALID")
    if (
        parsed_row_count is None
        or parsed_row_count < 0
        or quarantined_row_count is None
        or quarantined_row_count < 0
        or row_count is None
        or parsed_row_count + quarantined_row_count != row_count
    ):
        reasons.append("HISTORICAL_ARCHIVE_MANIFEST_COUNTS_MISMATCH")

    if schema_version != HISTORICAL_ARCHIVE_SCHEMA_VERSIONS.get(source_dataset or ""):
        reasons.append("HISTORICAL_ARCHIVE_MANIFEST_SCHEMA_UNSUPPORTED")

    if not (
        identity_valid
        and checksum_valid
        and byte_size is not None
        and byte_size > 0
        and row_count is not None
        and row_count > 0
        and parsed_row_count is not None
        and parsed_row_count >= 0
        and quarantined_row_count is not None
        and quarantined_row_count >= 0
        and parsed_row_count + quarantined_row_count == row_count
        and source_dataset is not None
        and schema_version == HISTORICAL_ARCHIVE_SCHEMA_VERSIONS.get(source_dataset)
    ):
        return None

    assert archive_key is not None
    assert bucket_name is not None
    assert object_key is not None
    assert content_sha256 is not None
    assert schema_version is not None
    assert source_dataset is not None
    assert byte_size is not None
    assert row_count is not None

    expected_archive_key = sha256(
        f"{bucket_name}\0{object_key}".encode("utf-8")
    ).hexdigest()
    if archive_key != expected_archive_key:
        reasons.append("HISTORICAL_ARCHIVE_ARCHIVE_KEY_MISMATCH")
        return None

    return _ManifestRecord(
        raw=dict(row),
        archive_key=archive_key,
        bucket_name=bucket_name,
        object_key=object_key,
        content_sha256=content_sha256,
        byte_size=byte_size,
        row_count=row_count,
        schema_version=schema_version,
        source_dataset=source_dataset,
    )


def _audit_reader_result(
    record: _ManifestRecord,
    inspection: HistoricalArchiveInspection,
    reasons: list[str],
) -> None:
    digest: object = inspection.content_sha256
    byte_size: object = inspection.byte_size
    row_count: object = inspection.row_count
    schema_version: object = inspection.schema_version
    if (
        not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
        or not isinstance(byte_size, int)
        or isinstance(byte_size, bool)
        or byte_size <= 0
        or not isinstance(row_count, int)
        or isinstance(row_count, bool)
        or row_count <= 0
        or not isinstance(schema_version, str)
    ):
        reasons.append("HISTORICAL_ARCHIVE_READER_RESULT_INVALID")
        return
    if digest != record.content_sha256:
        reasons.append("HISTORICAL_ARCHIVE_CHECKSUM_MISMATCH")
    if byte_size != record.byte_size:
        reasons.append("HISTORICAL_ARCHIVE_BYTE_SIZE_MISMATCH")
    if row_count != record.row_count:
        reasons.append("HISTORICAL_ARCHIVE_ROW_COUNT_MISMATCH")
    if schema_version != record.schema_version:
        reasons.append("HISTORICAL_ARCHIVE_SCHEMA_MISMATCH")


def _inspect_record(
    record: _ManifestRecord,
    reader: HistoricalArchiveObjectReader,
) -> tuple[str, ...]:
    reasons: list[str] = []
    try:
        inspection = reader.read(record.raw)
        _audit_reader_result(record, inspection, reasons)
    except HistoricalArchiveReadError as error:
        reasons.append(error.reason_code)
    except Exception:
        reasons.append("HISTORICAL_ARCHIVE_OBJECT_READ_FAILED")
    return tuple(reasons)


def audit_historical_archive(
    manifest_rows: Iterable[Mapping[str, object]],
    *,
    reader: HistoricalArchiveObjectReader,
    max_workers: int = 1,
    batch_size: int = 64,
    progress_callback: (
        Callable[[int, int | None, int, int, tuple[str, ...]], None] | None
    ) = None,
) -> HistoricalArchiveAuditResult:
    """Audit every object with bounded parallelism and deterministic evidence."""

    if not 1 <= max_workers <= 16:
        raise ValueError("max_workers must be between 1 and 16")
    if not max_workers <= batch_size <= 1_000:
        raise ValueError("batch_size must be between max_workers and 1000")

    rows = list(manifest_rows)
    reasons: list[str] = []
    if not rows:
        reasons.append("HISTORICAL_ARCHIVE_MANIFEST_EMPTY")

    records: list[_ManifestRecord] = []
    total_rows = 0
    total_bytes = 0
    archive_keys: set[str] = set()
    object_locations: set[tuple[str, str]] = set()

    for row in rows:
        row_count = _integer(row, "row_count")
        byte_size = _integer(row, "byte_size")
        if row_count is not None and row_count > 0:
            total_rows += row_count
        if byte_size is not None and byte_size > 0:
            total_bytes += byte_size

        record = _manifest_record(row, reasons)
        if record is None:
            continue
        if record.archive_key in archive_keys:
            reasons.append("HISTORICAL_ARCHIVE_DUPLICATE_ARCHIVE_KEY")
        archive_keys.add(record.archive_key)
        location = (record.bucket_name, record.object_key)
        if location in object_locations:
            reasons.append("HISTORICAL_ARCHIVE_DUPLICATE_OBJECT_KEY")
        object_locations.add(location)
        records.append(record)

    inspected = inspected_rows = inspected_bytes = 0

    def inspect(record: _ManifestRecord) -> tuple[str, ...]:
        return _inspect_record(record, reader)

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="historical-r2-audit",
    ) as executor:
        for offset in range(0, len(records), batch_size):
            batch = records[offset : offset + batch_size]
            for record, batch_reasons in zip(batch, executor.map(inspect, batch)):
                reasons.extend(batch_reasons)
                inspected_rows += record.row_count
                inspected_bytes += record.byte_size
            inspected += len(batch)
            if progress_callback is not None:
                progress_callback(
                    inspected,
                    _integer(batch[-1].raw, "archive_id"),
                    inspected_rows,
                    inspected_bytes,
                    tuple(dict.fromkeys(reasons)),
                )

    unique_reasons = tuple(dict.fromkeys(reasons))
    return HistoricalArchiveAuditResult(
        passed=not unique_reasons,
        status="PASS" if not unique_reasons else "FAIL",
        object_count=len(rows),
        row_count=total_rows,
        byte_count=total_bytes,
        reason_codes=unique_reasons,
    )
