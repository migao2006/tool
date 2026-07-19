from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pyarrow as pa
import pyarrow.parquet as pq

from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_supplemental_normalizer import (
    normalize_historical_supplemental,
)
from src.data.ingestion.historical_supplemental_parquet import (
    serialize_historical_supplemental_parquet,
)
from src.data.providers.contracts import ProviderPayload


def _payload(dataset: str) -> ProviderPayload:
    body = {
        "status": 200,
        "data": [{"date": "2021-07-19", "stock_id": "2330", "value": 123}],
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset=dataset,
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


def test_dataset_specific_object_key_schema_and_zstd_payload() -> None:
    payload = _payload("institutional_flows")
    batch = normalize_historical_supplemental(payload)
    request = HistoricalArchiveRequest(
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        source_symbol="2330",
        requested_start_date=date(2021, 7, 19),
        requested_end_date=date(2026, 7, 17),
        source_payload_sha256=payload.payload_sha256,
        retrieved_at=payload.retrieved_at,
        source_dataset=payload.dataset,
    )

    artifact = serialize_historical_supplemental_parquet(
        batch.landing_rows,
        request=request,
    )

    assert "/dataset=institutional_flows/" in artifact.object_key
    assert artifact.schema_version == "historical_institutional_flows.v1"
    assert artifact.content_sha256 == sha256(artifact.payload).hexdigest()
    parquet = pq.ParquetFile(pa.BufferReader(artifact.payload))
    assert parquet.metadata.num_rows == 1
    assert {
        parquet.metadata.row_group(0).column(index).compression
        for index in range(parquet.metadata.num_columns)
    } == {"ZSTD"}
    metadata = parquet.schema_arrow.metadata or {}
    assert metadata[b"archive.source_dataset"] == b"institutional_flows"
    record = parquet.read().to_pylist()[0]
    assert json.loads(record["source_row"])["stock_id"] == "2330"
