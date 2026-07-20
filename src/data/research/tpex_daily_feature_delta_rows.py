"""Row adaptation for TPEX daily feature delta artifacts."""

from __future__ import annotations

from datetime import datetime, time, timezone
import json
from typing import cast
from zoneinfo import ZoneInfo

from src.features.price_volume_contracts import PriceVolumeFeatureRow

from .archive_feature_contracts import CurrentSecurityIdentity
from .archive_feature_rows import SourceProvenance, output_row
from .tpex_daily_bar_contracts import TpexDailyBar
from .tpex_daily_feature_delta_contracts import TPEX_DAILY_FEATURE_DELTA_REASONS


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_TIME = time(17, 0)
DAILY_SOURCE_REASONS = (
    "POINT_IN_TIME_UNVERIFIED",
    "RAW_POINT_IN_TIME_UNVERIFIED",
    "RAW_AVAILABLE_AT_FIRST_OBSERVED_ONLY",
)


def daily_record(
    row: TpexDailyBar,
    identity: CurrentSecurityIdentity,
) -> dict[str, object]:
    return {
        "security_id": identity.security_id,
        "listing_period_id": identity.listing_period_id,
        "market": "TPEX",
        "symbol": identity.symbol,
        "asset_type": "COMMON_STOCK",
        "trade_date": row.trade_date,
        "decision_at": datetime.combine(
            row.trade_date,
            DECISION_TIME,
            tzinfo=TAIPEI,
        ),
        "available_at": row.available_at,
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "close_price": row.close_price,
        "trading_volume": row.trading_volume,
        "trading_value": row.trading_value,
        "point_in_time_status": "UNVERIFIED",
        "parse_status": "PARSED",
        "reason_codes": DAILY_SOURCE_REASONS,
    }


def delta_output_row(
    feature: PriceVolumeFeatureRow,
    *,
    identity: CurrentSecurityIdentity,
    history: SourceProvenance,
    daily: TpexDailyBar,
    dataset_snapshot_sha256: str,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
    daily_bar_snapshot_sha256: str,
) -> dict[str, object]:
    row = output_row(
        feature,
        identity=identity,
        provenance=history,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        source_archive_snapshot_sha256=source_archive_snapshot_sha256,
        current_identity_snapshot_sha256=current_identity_snapshot_sha256,
        market="TPEX",
    )
    existing = cast(list[str], json.loads(cast(str, row["reason_codes"])))
    row.update(
        daily_bar_snapshot_sha256=daily_bar_snapshot_sha256,
        source_daily_bar_id=daily.daily_bar_id,
        source_daily_source_id=daily.source_id,
        source_daily_version=daily.source_version,
        source_daily_available_at=daily.available_at.astimezone(timezone.utc),
        reason_codes=json.dumps(
            tuple(dict.fromkeys((*TPEX_DAILY_FEATURE_DELTA_REASONS, *existing))),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    return row


__all__ = ["daily_record", "delta_output_row"]
