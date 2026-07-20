"""Build a manifest-ready TPEx OHLC archive without external writes."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from hashlib import sha256

from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.providers.tpex import TPEX_MONTHLY_OHLC_DATASET

from .historical_archive_contracts import (
    HistoricalArchiveArtifact,
    HistoricalArchiveRequest,
)
from .tpex_ohlc_contracts import TPEX_OHLC_SYMBOL, NormalizedTpexOhlcBatch
from .tpex_ohlc_parquet import serialize_tpex_ohlc_parquet


def build_tpex_ohlc_archive(
    batch: NormalizedTpexOhlcBatch,
) -> HistoricalArchiveArtifact:
    """Create the immutable R2 object plan for one official calendar month."""

    end_date = date(
        batch.requested_month.year,
        batch.requested_month.month,
        monthrange(batch.requested_month.year, batch.requested_month.month)[1],
    )
    request = HistoricalArchiveRequest(
        provider_code="TPEX",
        source_dataset=TPEX_MONTHLY_OHLC_DATASET,
        scheduled_market="TPEX",
        asset_type="BENCHMARK",
        source_symbol=TPEX_OHLC_SYMBOL,
        requested_start_date=batch.requested_month,
        requested_end_date=end_date,
        source_payload_sha256=batch.source_payload_sha256,
        retrieved_at=batch.retrieved_at,
    )
    return serialize_tpex_ohlc_parquet(batch, request=request)


def build_tpex_ohlc_manifest(
    batch: NormalizedTpexOhlcBatch,
    artifact: HistoricalArchiveArtifact,
    *,
    bucket_name: str,
    object_etag: str | None,
) -> HistoricalArchiveManifest:
    """Bind a verified object location to its research-only manifest."""

    request = artifact.request
    if (
        request.provider_code != "TPEX"
        or request.source_dataset != TPEX_MONTHLY_OHLC_DATASET
        or request.scheduled_market != "TPEX"
        or request.asset_type != "BENCHMARK"
        or request.source_symbol != TPEX_OHLC_SYMBOL
        or request.source_payload_sha256 != batch.source_payload_sha256
        or artifact.row_count != len(batch.rows)
    ):
        raise ValueError("TPEx artifact does not match the normalized batch")
    trade_dates = [row.trade_date for row in batch.rows]
    object_key = artifact.object_key
    archive_key = sha256(f"{bucket_name}\0{object_key}".encode()).hexdigest()
    return HistoricalArchiveManifest(
        archive_key=archive_key,
        storage_provider="CLOUDFLARE_R2",
        bucket_name=bucket_name,
        object_key=object_key,
        object_etag=object_etag,
        schema_version=artifact.schema_version,
        provider_code=request.provider_code,
        source_dataset=request.source_dataset,
        source_version=batch.source_version,
        source_symbol=request.source_symbol,
        scheduled_market=request.scheduled_market,
        asset_type=request.asset_type,
        requested_start_date=request.requested_start_date,
        requested_end_date=request.requested_end_date,
        min_trade_date=min(trade_dates),
        max_trade_date=max(trade_dates),
        source_payload_hash=request.source_payload_sha256,
        parquet_sha256=artifact.content_sha256,
        byte_size=artifact.byte_size,
        row_count=artifact.row_count,
        parsed_row_count=artifact.row_count,
        quarantined_row_count=0,
        first_observed_at=request.retrieved_at,
        point_in_time_status=batch.point_in_time_status,
        usage_scope=batch.usage_scope,
        system_status=batch.system_status,
        reason_codes=batch.reason_codes,
    )
