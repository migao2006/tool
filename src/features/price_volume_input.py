"""Input validation for venue-scoped price/volume research features."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from numbers import Integral
from typing import cast
from zoneinfo import ZoneInfo

from .price_volume_schema import price_volume_feature_spec
from .price_volume_availability import (
    AvailabilityMode,
    partition_source_reasons,
    resolve_availability,
)
from .price_volume_record_adapter import (
    MISSING,
    available_at_basis as read_available_at_basis,
    date_value,
    datetime_value,
    market_value,
    materialize_records as materialize_canonical_records,
    observed_available_at,
    optional_number,
    read_field,
    required_text,
    source_reason_codes,
)


TAIPEI = ZoneInfo("Asia/Taipei")
_NUMERIC_FIELDS = (
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "trading_volume",
    "trading_value",
)


class FeatureInputError(ValueError):
    """A fail-closed field error preserved in feature audits."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code: str = reason_code


@dataclass(frozen=True)
class CanonicalResearchBar:
    """The canonical fields required by dependency-light feature formulas."""

    security_id: int
    listing_period_id: str
    market: str
    symbol: str
    trade_date: date
    decision_at: datetime
    availability_mode: AvailabilityMode
    available_at: datetime
    observed_available_at: datetime
    available_at_basis: str | None
    values: Mapping[str, float | None]
    field_reason_codes: Mapping[str, tuple[str, ...]]
    record_reason_codes: tuple[str, ...]
    record_research_limitation_reason_codes: tuple[str, ...]

    def value(self, field_name: str) -> float:
        value = self.values[field_name]
        if value is None:
            reasons = self.field_reason_codes.get(field_name, ())
            raise FeatureInputError(
                reasons[0] if reasons else f"FEATURE_INPUT_INVALID:{field_name}"
            )
        return value


def _security_id(record: object) -> int:
    value = read_field(record, "security_id")
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError("security_id must be a positive integer")
    return int(value)


def _numeric_fields(
    record: object,
) -> tuple[dict[str, float | None], dict[str, tuple[str, ...]]]:
    values: dict[str, float | None] = {}
    reasons_by_field: dict[str, tuple[str, ...]] = {}
    for field_name in _NUMERIC_FIELDS:
        value, reasons = optional_number(
            record,
            field_name,
            nonnegative=field_name in {"trading_volume", "trading_value"},
        )
        values[field_name] = value
        reasons_by_field[field_name] = reasons
    return values, reasons_by_field


def parse_canonical_bar(
    record: object,
    *,
    availability_mode: AvailabilityMode,
    expected_market: str = "TWSE",
) -> CanonicalResearchBar:
    spec = price_volume_feature_spec(expected_market)
    security_id = _security_id(record)
    listing_period_id = required_text(record, "listing_period_id")
    symbol = required_text(record, "symbol")
    market = market_value(record)
    trade_date = date_value(read_field(record, "trade_date"), "trade_date")
    decision_at = read_field(record, "decision_at")
    parsed_decision_at = datetime_value(decision_at, "decision_at")
    observed_at, availability_reasons = observed_available_at(record)
    basis, basis_reasons = read_available_at_basis(record)
    availability = resolve_availability(
        observed_at=observed_at,
        trade_date=trade_date,
        available_at_basis=basis,
        availability_mode=availability_mode,
        evidence_reason_codes=(*availability_reasons, *basis_reasons),
    )
    field_values, field_reasons = _numeric_fields(record)

    source_reasons = list(source_reason_codes(record))
    point_in_time_status = read_field(record, "point_in_time_status")
    if point_in_time_status is not MISSING and point_in_time_status != "VERIFIED":
        source_reasons.append("CANONICAL_POINT_IN_TIME_UNVERIFIED")
    source_hard, source_limitations = partition_source_reasons(
        tuple(source_reasons),
        availability_mode=availability_mode,
        available_at_basis=basis,
    )
    hard_reasons = [*source_hard, *availability.hard_fail_reason_codes]
    limitations = [
        *source_limitations,
        *availability.research_limitation_reason_codes,
    ]
    if market != spec.market:
        hard_reasons.append(spec.market_required_reason)
    asset_type = read_field(record, "asset_type")
    if asset_type is not MISSING and asset_type is not None:
        normalized_asset_type = str(getattr(asset_type, "value", asset_type))
        if normalized_asset_type != "COMMON_STOCK":
            hard_reasons.append(spec.common_stock_required_reason)
    parse_status = read_field(record, "parse_status")
    if parse_status is not MISSING and parse_status != "PARSED":
        hard_reasons.append("CANONICAL_BAR_NOT_PARSED")
    if parsed_decision_at.astimezone(TAIPEI).date() != trade_date:
        hard_reasons.append("DECISION_DATE_MISMATCH")

    ohlc = tuple(field_values[name] for name in _NUMERIC_FIELDS[:4])
    if all(value is not None for value in ohlc):
        opening, high, low, closing = cast(
            tuple[float, float, float, float],
            ohlc,
        )
        if low > min(opening, closing) or high < max(opening, closing) or low > high:
            hard_reasons.append("CANONICAL_OHLC_INVALID")
    return CanonicalResearchBar(
        security_id=security_id,
        listing_period_id=listing_period_id,
        market=market,
        symbol=symbol,
        trade_date=trade_date,
        decision_at=parsed_decision_at,
        availability_mode=availability_mode,
        available_at=availability.effective_at,
        observed_available_at=availability.observed_at,
        available_at_basis=basis,
        values=field_values,
        field_reason_codes=field_reasons,
        record_reason_codes=tuple(dict.fromkeys(hard_reasons)),
        record_research_limitation_reason_codes=tuple(dict.fromkeys(limitations)),
    )


def resolve_trading_sessions(
    bars: Sequence[CanonicalResearchBar],
    trading_sessions: Sequence[date] | None,
) -> tuple[date, ...]:
    sessions = (
        tuple(date_value(value, "trading_session") for value in trading_sessions)
        if trading_sessions is not None
        else tuple(sorted({bar.trade_date for bar in bars}))
    )
    if tuple(sorted(set(sessions))) != sessions:
        raise ValueError("trading_sessions must be sorted and unique")
    if {bar.trade_date for bar in bars}.difference(sessions):
        raise ValueError("trading_sessions do not contain every canonical bar date")
    return sessions


def deduplicate_listing_bars(
    bars: Sequence[CanonicalResearchBar],
) -> dict[date, CanonicalResearchBar]:
    grouped: dict[date, list[CanonicalResearchBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.trade_date, []).append(bar)
    output: dict[date, CanonicalResearchBar] = {}
    identities = {(bar.security_id, bar.market, bar.symbol) for bar in bars}
    identity_reasons = () if len(identities) == 1 else ("LISTING_IDENTITY_CONFLICT",)
    for trade_date, candidates in grouped.items():
        reasons = [*candidates[0].record_reason_codes, *identity_reasons]
        if len(candidates) != 1:
            reasons.append("DUPLICATE_CANONICAL_BAR")
        output[trade_date] = replace(
            candidates[0],
            record_reason_codes=tuple(dict.fromkeys(reasons)),
        )
    return output


__all__ = [
    "CanonicalResearchBar",
    "FeatureInputError",
    "deduplicate_listing_bars",
    "materialize_canonical_records",
    "parse_canonical_bar",
    "resolve_trading_sessions",
]
