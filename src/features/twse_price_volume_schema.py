"""Frozen schema metadata for the TWSE raw price/volume feature set."""

from __future__ import annotations

from hashlib import sha256
import json


TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION = "twse-raw-price-volume-5d-v1"
TWSE_PRICE_VOLUME_PRICE_BASIS = "UNADJUSTED_RAW_CLOSE"
TWSE_PRICE_VOLUME_AVAILABILITY_MODES = (
    "STRICT_CANONICAL",
    "RESEARCH_SCHEDULING_HINT",
)
TWSE_RESEARCH_SCHEDULING_HINT_REASON = "RESEARCH_SCHEDULING_HINT"

_RETURN_WINDOWS = (1, 2, 3, 5, 10, 20, 60)
TWSE_PRICE_VOLUME_FEATURE_FORMULAS: tuple[tuple[str, str], ...] = (
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
TWSE_PRICE_VOLUME_FEATURE_NAMES = tuple(
    name for name, _ in TWSE_PRICE_VOLUME_FEATURE_FORMULAS
)


def _feature_schema_hash() -> str:
    payload = {
        "available_at_rule": "max(source_bar.available_at) <= decision_at",
        "availability_modes": TWSE_PRICE_VOLUME_AVAILABILITY_MODES,
        "features": [
            {"name": name, "formula": formula}
            for name, formula in TWSE_PRICE_VOLUME_FEATURE_FORMULAS
        ],
        "horizon": 5,
        "market": "TWSE",
        "price_basis": TWSE_PRICE_VOLUME_PRICE_BASIS,
        "schema_version": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
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


TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH = _feature_schema_hash()


__all__ = [
    "TWSE_PRICE_VOLUME_AVAILABILITY_MODES",
    "TWSE_PRICE_VOLUME_FEATURE_FORMULAS",
    "TWSE_PRICE_VOLUME_FEATURE_NAMES",
    "TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH",
    "TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION",
    "TWSE_PRICE_VOLUME_PRICE_BASIS",
    "TWSE_RESEARCH_SCHEDULING_HINT_REASON",
]
