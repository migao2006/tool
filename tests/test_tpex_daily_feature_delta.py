from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import cast

import pyarrow.parquet as pq
import pytest

from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_SCHEMA_VERSION,
)
from src.data.research.archive_feature_contracts import (
    CurrentSecurityIdentity,
    IdentitySnapshot,
    identity_snapshot_hash,
)
from src.data.research.tpex_daily_bar_contracts import (
    TpexDailyBar,
    TpexDailyBarRevision,
    TpexDailyBarSeriesSnapshot,
    daily_bar_revision_hash,
    daily_bar_series_hash,
)
from src.data.research.tpex_daily_feature_delta_artifact import (
    TpexDailyFeatureDeltaWriter,
)
from src.data.research.tpex_daily_feature_delta_builder import (
    TpexDailyFeatureDeltaBuilder,
    daily_delta_start_date,
)
from src.data.research.tpex_daily_feature_delta_contracts import (
    TPEX_DAILY_FEATURE_DELTA_REASONS,
    TpexDailyFeatureDeltaError,
    daily_feature_delta_snapshot_hash,
)
from src.data.research.tpex_daily_feature_delta_reader import (
    TpexDailyFeatureDeltaReader,
)
from src.features.tpex_price_volume_schema import TPEX_PRICE_VOLUME_FEATURE_NAMES


START_DATE = date(2026, 5, 14)
ARCHIVE_END = date(2026, 7, 17)
DELTA_DATE = date(2026, 7, 20)
OBSERVED_AT = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
SOURCE_ARCHIVE_SNAPSHOT = "a" * 64
BUCKET = "alpha-lens-archive"


def _source_row(index: int) -> dict[str, object]:
    trade_date = START_DATE + timedelta(days=index)
    close = 50.0 + index / 10
    return {
        "parse_status": "PARSED",
        "trade_date": trade_date,
        "available_at": OBSERVED_AT,
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "open_price": close - 0.1,
        "high_price": close + 0.3,
        "low_price": close - 0.3,
        "close_price": close,
        "trading_volume": 500_000.0 + index,
        "trading_value": close * (500_000.0 + index),
        "reason_codes": json.dumps(["POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"]),
    }


def _manifest() -> dict[str, object]:
    object_key = "historical/finmind/daily_bars/tpex/5483.parquet"
    return {
        "archive_id": 1,
        "archive_key": sha256(f"{BUCKET}\0{object_key}".encode()).hexdigest(),
        "storage_provider": "CLOUDFLARE_R2",
        "bucket_name": BUCKET,
        "object_key": object_key,
        "object_etag": '"etag"',
        "schema_version": HISTORICAL_ARCHIVE_SCHEMA_VERSION,
        "provider_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_version": "api.v4",
        "source_symbol": "5483",
        "scheduled_market": "TPEX",
        "asset_type": "COMMON_STOCK",
        "requested_start_date": START_DATE.isoformat(),
        "requested_end_date": ARCHIVE_END.isoformat(),
        "min_trade_date": START_DATE.isoformat(),
        "max_trade_date": ARCHIVE_END.isoformat(),
        "source_payload_hash": "b" * 64,
        "parquet_sha256": "c" * 64,
        "byte_size": 1,
        "row_count": 65,
        "parsed_row_count": 65,
        "quarantined_row_count": 0,
        "first_observed_at": OBSERVED_AT.isoformat(),
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": ["POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"],
    }


class _Reader:
    def __init__(self, rows: tuple[dict[str, object], ...]) -> None:
        self.rows = rows

    def read(self, values: object) -> object:
        manifest = HistoricalArchiveManifest.from_mapping(
            cast(dict[str, object], values)
        )
        return SimpleNamespace(rows=self.rows, manifest=manifest)


def _inputs() -> tuple[
    HistoricalArchiveManifestSnapshot,
    IdentitySnapshot,
    TpexDailyBarSeriesSnapshot,
]:
    raw_manifest = _manifest()
    manifests = HistoricalArchiveManifestSnapshot(
        rows=(MappingProxyType(raw_manifest),),
        snapshot_sha256=SOURCE_ARCHIVE_SNAPSHOT,
        complete=True,
    )
    identity = CurrentSecurityIdentity(
        security_id=5483,
        symbol="5483",
        listing_date=date(2003, 1, 2),
        market="TPEX",
    )
    identities = IdentitySnapshot(
        by_symbol={identity.symbol: identity},
        snapshot_sha256=identity_snapshot_hash({identity.symbol: identity}),
    )
    daily = TpexDailyBar(
        daily_bar_id=7001,
        security_id=identity.security_id,
        trade_date=DELTA_DATE,
        open_price=56.4,
        high_price=57.2,
        low_price=56.1,
        close_price=56.8,
        trading_volume=800_000.0,
        trading_value=45_440_000.0,
        source_id=2,
        source_version="official-20260720-abcdef01",
        available_at=OBSERVED_AT,
    )
    revision_rows = (daily,)
    revision = TpexDailyBarRevision(
        as_of_date=DELTA_DATE,
        source_id=2,
        source_version=daily.source_version,
        rows=revision_rows,
        snapshot_sha256=daily_bar_revision_hash(
            as_of_date=DELTA_DATE,
            source_id=2,
            source_version=daily.source_version,
            rows=revision_rows,
        ),
    )
    revisions = (revision,)
    daily_bars = TpexDailyBarSeriesSnapshot(
        revisions=revisions,
        snapshot_sha256=daily_bar_series_hash(revisions),
    )
    return manifests, identities, daily_bars


def test_builder_creates_exact_date_read_back_verified_delta(tmp_path: Path) -> None:
    manifests, identities, daily_bars = _inputs()
    output = tmp_path / "tpex-daily-feature-delta.parquet"
    dataset_hash = daily_feature_delta_snapshot_hash(
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
        daily_bar_snapshot_sha256=daily_bars.snapshot_sha256,
        as_of_date=DELTA_DATE,
    )
    writer = TpexDailyFeatureDeltaWriter(
        output,
        dataset_snapshot_sha256=dataset_hash,
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
        daily_bar_snapshot_sha256=daily_bars.snapshot_sha256,
        as_of_date=DELTA_DATE,
    )

    audit = TpexDailyFeatureDeltaBuilder(
        cast(object, _Reader(tuple(_source_row(index) for index in range(65)))),
        now_fn=lambda: OBSERVED_AT,
    ).build(
        manifests=manifests,
        identities=identities,
        daily_bars=daily_bars,
        writer=writer,
    )
    reader = TpexDailyFeatureDeltaReader()
    artifact = reader.manifest_from_parquet(output)
    verified = reader.verify(output, artifact)
    assert verified.path == output
    assert verified.manifest == artifact

    table = pq.read_table(output)
    assert artifact.as_of_date == DELTA_DATE
    assert artifact.dataset_snapshot_sha256 == dataset_hash
    assert artifact.row_count == audit.output_row_count == 1
    assert table["decision_date"].to_pylist() == [DELTA_DATE]
    assert table["source_daily_bar_id"].to_pylist() == [7001]
    assert table["source_daily_version"].to_pylist() == ["official-20260720-abcdef01"]
    assert table["source_daily_available_at"].to_pylist() == [OBSERVED_AT]
    assert all(
        table[name][0].as_py() is not None for name in TPEX_PRICE_VOLUME_FEATURE_NAMES
    )
    reasons = json.loads(table["reason_codes"][0].as_py())
    assert set(TPEX_DAILY_FEATURE_DELTA_REASONS).issubset(reasons)
    assert table.schema.metadata[b"system.status"] == b"RESEARCH_ONLY"
    assert table.schema.metadata[b"point_in_time.status"] == b"UNVERIFIED"
    assert daily_delta_start_date(manifests) == date(2026, 7, 18)


def test_delta_fails_closed_when_exact_date_is_not_newer_than_archive(
    tmp_path: Path,
) -> None:
    manifests, identities, daily_bars = _inputs()
    old_row = daily_bars.revisions[0].rows[0]
    old_row = TpexDailyBar(
        **{
            **old_row.__dict__,
            "trade_date": ARCHIVE_END,
        }
    )
    rows = (old_row,)
    revision = TpexDailyBarRevision(
        as_of_date=ARCHIVE_END,
        source_id=2,
        source_version=old_row.source_version,
        rows=rows,
        snapshot_sha256=daily_bar_revision_hash(
            as_of_date=ARCHIVE_END,
            source_id=2,
            source_version=old_row.source_version,
            rows=rows,
        ),
    )
    stale = TpexDailyBarSeriesSnapshot(
        revisions=(revision,),
        snapshot_sha256=daily_bar_series_hash((revision,)),
    )
    writer = TpexDailyFeatureDeltaWriter(
        tmp_path / "must-not-exist.parquet",
        dataset_snapshot_sha256=daily_feature_delta_snapshot_hash(
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
            daily_bar_snapshot_sha256=stale.snapshot_sha256,
            as_of_date=ARCHIVE_END,
        ),
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
        daily_bar_snapshot_sha256=stale.snapshot_sha256,
        as_of_date=ARCHIVE_END,
    )

    with pytest.raises(TpexDailyFeatureDeltaError) as captured:
        _ = TpexDailyFeatureDeltaBuilder(
            cast(object, _Reader(tuple(_source_row(index) for index in range(65))))
        ).build(
            manifests=manifests,
            identities=identities,
            daily_bars=stale,
            writer=writer,
        )

    assert captured.value.reason_code == (
        "TPEX_DAILY_FEATURE_DELTA_NOT_NEWER_THAN_ARCHIVE"
    )
    assert not writer.output_path.exists()
    assert not writer.partial_path.exists()
