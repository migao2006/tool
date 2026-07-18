from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_parquet_serializer import (
    historical_parquet_schema,
    serialize_historical_parquet,
)


SOURCE_PAYLOAD_HASH = "c" * 64
OBSERVED_AT = datetime(2026, 7, 18, 6, tzinfo=timezone.utc)


def _request() -> HistoricalArchiveRequest:
    return HistoricalArchiveRequest(
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        source_symbol="2330",
        requested_start_date=date(2020, 1, 1),
        requested_end_date=date(2026, 7, 18),
        source_payload_sha256=SOURCE_PAYLOAD_HASH,
        retrieved_at=OBSERVED_AT,
    )


def _row(index: int, **updates: object) -> dict[str, object]:
    trade_day = date(2020, 1, 2 + index)
    row: dict[str, object] = {
        "landing_key": f"{index + 1:064x}",
        "source_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_symbol": "2330",
        "source_market_claim": None,
        "source_market_basis": "UNAVAILABLE",
        "source_version": "api.v4",
        "source_revision_hash": f"{index + 11:064x}",
        "source_payload_hash": SOURCE_PAYLOAD_HASH,
        "source_url": "https://api.finmindtrade.com/api/v4/data",
        "source_row_index": index,
        "source_row": {
            "stock_name": "台積電",
            "stock_id": "2330",
            "date": trade_day.isoformat(),
        },
        "first_observed_at": OBSERVED_AT.isoformat(),
        "available_at": OBSERVED_AT.isoformat(),
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "identity_resolution_status": "UNRESOLVED",
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": [
            "SOURCE_MARKET_UNAVAILABLE",
            "RAW_LANDING_ONLY",
        ],
        "source_trade_date": trade_day.isoformat(),
        "trade_date": trade_day.isoformat(),
        "parse_status": "PARSED",
        "open_price": "332.5",
        "high_price": "339.0",
        "low_price": "332.5",
        "close_price": "339.0",
        "trading_volume": "34000000",
        "trading_value": "11500000000",
        "trade_count": 30115,
    }
    row.update(updates)
    return row


def test_serializer_writes_fixed_zstd_schema_and_integrity_metadata() -> None:
    artifact = serialize_historical_parquet([_row(0), _row(1)], request=_request())

    assert artifact.byte_size == len(artifact.payload)
    assert artifact.content_sha256 == sha256(artifact.payload).hexdigest()
    assert artifact.row_count == 2
    parquet_file = pq.ParquetFile(pa.BufferReader(artifact.payload))
    assert parquet_file.metadata.num_rows == 2
    assert {
        parquet_file.metadata.row_group(0).column(index).compression
        for index in range(parquet_file.metadata.num_columns)
    } == {"ZSTD"}

    table = parquet_file.read()
    assert table.schema.names == historical_parquet_schema().names
    metadata = table.schema.metadata or {}
    assert metadata[b"archive.schema_version"] == b"historical_daily_bars.v1"
    assert metadata[b"scheduled_market.semantics"] == b"request-scheduling-only"
    assert metadata[b"archive.scheduled_market"] == b"TWSE"
    assert metadata[b"archive.source_payload_sha256"] == SOURCE_PAYLOAD_HASH.encode()


def test_serializer_preserves_canonical_json_without_claiming_market_identity() -> None:
    source_row = {
        "z": 2,
        "中文": "保留",
        "nested": {"b": True, "a": None},
    }
    reasons = ["RAW_LANDING_ONLY", "POINT_IN_TIME_UNVERIFIED"]
    issues = [{"reason_code": "TRADE_DATE_INVALID", "field_name": "date"}]
    artifact = serialize_historical_parquet(
        [
            _row(
                0,
                source_row=source_row,
                reason_codes=reasons,
                archive_quarantine_issues=issues,
            )
        ],
        request=_request(),
    )

    record = pq.read_table(pa.BufferReader(artifact.payload)).to_pylist()[0]
    assert record["source_row"] == json.dumps(
        source_row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert record["reason_codes"] == '["RAW_LANDING_ONLY","POINT_IN_TIME_UNVERIFIED"]'
    assert record["quarantine_issues"] == json.dumps(
        issues,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert record["scheduled_market"] == "TWSE"
    assert record["source_market_claim"] is None


def test_serializer_is_deterministic_for_the_same_normalized_rows() -> None:
    first = serialize_historical_parquet([_row(1), _row(0)], request=_request())
    second = serialize_historical_parquet([_row(0), _row(1)], request=_request())

    assert first.object_key == second.object_key
    assert first.content_sha256 == second.content_sha256
    assert first.payload == second.payload


def test_serializer_rejects_mismatched_provenance_and_non_json_source_rows() -> None:
    with pytest.raises(IngestionError) as hash_error:
        serialize_historical_parquet(
            [_row(0, source_payload_hash="d" * 64)],
            request=_request(),
        )
    assert hash_error.value.reason_code == "HISTORICAL_ARCHIVE_PAYLOAD_HASH_MISMATCH"

    with pytest.raises(IngestionError) as symbol_error:
        serialize_historical_parquet(
            [_row(0, source_symbol="2317")],
            request=_request(),
        )
    assert symbol_error.value.reason_code == "HISTORICAL_ARCHIVE_SYMBOL_MISMATCH"

    with pytest.raises(IngestionError) as json_error:
        serialize_historical_parquet(
            [_row(0, source_row={"invalid": float("nan")})],
            request=_request(),
        )
    assert json_error.value.reason_code == "HISTORICAL_ARCHIVE_JSON_INVALID"


def test_serializer_rejects_empty_archives() -> None:
    with pytest.raises(IngestionError) as captured:
        serialize_historical_parquet([], request=_request())

    assert captured.value.reason_code == "HISTORICAL_ARCHIVE_EMPTY"
