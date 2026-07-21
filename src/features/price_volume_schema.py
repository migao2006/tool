"""Shared 17-feature price/volume schema for Taiwan common-stock venues."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json


PRICE_VOLUME_PRICE_BASIS = "UNADJUSTED_RAW_CLOSE"
PRICE_VOLUME_AVAILABILITY_MODES = (
    "STRICT_CANONICAL",
    "RESEARCH_SCHEDULING_HINT",
)
RESEARCH_SCHEDULING_HINT_REASON = "RESEARCH_SCHEDULING_HINT"

_RETURN_WINDOWS = (1, 2, 3, 5, 10, 20, 60)
PRICE_VOLUME_FEATURE_FORMULAS: tuple[tuple[str, str], ...] = (
    *tuple(
        (
            f"raw_close_return_{window}d",
            f"raw_close_t / raw_close_t_minus_{window}_sessions - 1",
        )
        for window in _RETURN_WINDOWS
    ),
    ("overnight_gap_1d", "raw_open_t / raw_close_t_minus_1_session - 1"),
    ("intraday_return_1d", "raw_close_t / raw_open_t - 1"),
    ("atr_14", "mean(true_range, trailing_14_sessions) / raw_close_t"),
    (
        "realized_volatility_20",
        "sqrt(sum(log(raw_close_t/raw_close_t_minus_1)^2, trailing_20_sessions))",
    ),
    (
        "downside_volatility_20",
        "sqrt(sum(min(log_return, 0)^2, trailing_20_sessions))",
    ),
    (
        "maximum_drawdown_20",
        "min(raw_close / trailing_raw_close_peak - 1, trailing_20_sessions)",
    ),
    ("adv20_ntd", "mean(trading_value_ntd, trailing_20_sessions)"),
    ("turnover_ntd_mean_20", "mean(trading_value_ntd, trailing_20_sessions)"),
    (
        "volume_anomaly_20",
        "trading_volume_t / median(trading_volume, trailing_20_sessions) - 1",
    ),
    (
        "amihud_illiquidity_20",
        "mean(abs(raw_close_return_1d) / trading_value_ntd, trailing_20_sessions)",
    ),
)
PRICE_VOLUME_FEATURE_NAMES = tuple(
    name for name, _ in PRICE_VOLUME_FEATURE_FORMULAS
)


@dataclass(frozen=True)
class PriceVolumeFeatureSpec:
    market: str
    schema_version: str
    schema_hash: str
    market_required_reason: str
    common_stock_required_reason: str


def price_volume_feature_schema_hash(*, market: str, schema_version: str) -> str:
    payload = {
        "available_at_rule": "max(source_bar.available_at) <= decision_at",
        "availability_modes": PRICE_VOLUME_AVAILABILITY_MODES,
        "features": [
            {"name": name, "formula": formula}
            for name, formula in PRICE_VOLUME_FEATURE_FORMULAS
        ],
        "horizon": 5,
        "market": market,
        "price_basis": PRICE_VOLUME_PRICE_BASIS,
        "schema_version": schema_version,
        "system_status": "RESEARCH_ONLY",
        "scheduling_hint_rule": (
            "FIRST_OBSERVED_AT_RETRIEVAL may use trade_date 16:00 Asia/Taipei "
            "only in explicit RESEARCH_SCHEDULING_HINT mode"
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _spec(market: str) -> PriceVolumeFeatureSpec:
    if market not in {"TWSE", "TPEX"}:
        raise ValueError("price/volume features support only TWSE or TPEX")
    schema_version = f"{market.lower()}-raw-price-volume-5d-v1"
    return PriceVolumeFeatureSpec(
        market=market,
        schema_version=schema_version,
        schema_hash=price_volume_feature_schema_hash(
            market=market,
            schema_version=schema_version,
        ),
        market_required_reason=f"{market}_MARKET_REQUIRED",
        common_stock_required_reason=f"{market}_COMMON_STOCK_REQUIRED",
    )


PRICE_VOLUME_FEATURE_SPECS = {
    market: _spec(market) for market in ("TWSE", "TPEX")
}


def price_volume_feature_spec(market: str) -> PriceVolumeFeatureSpec:
    try:
        return PRICE_VOLUME_FEATURE_SPECS[market]
    except KeyError as error:
        raise ValueError("price/volume features support only TWSE or TPEX") from error


__all__ = [
    "PRICE_VOLUME_AVAILABILITY_MODES",
    "PRICE_VOLUME_FEATURE_FORMULAS",
    "PRICE_VOLUME_FEATURE_NAMES",
    "PRICE_VOLUME_PRICE_BASIS",
    "RESEARCH_SCHEDULING_HINT_REASON",
    "PriceVolumeFeatureSpec",
    "price_volume_feature_schema_hash",
    "price_volume_feature_spec",
]
