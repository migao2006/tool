"""Shared raw price/volume construction for Taiwan common-stock venues."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from .price_volume_schema import (
    PRICE_VOLUME_FEATURE_NAMES,
    PRICE_VOLUME_PRICE_BASIS,
    price_volume_feature_spec,
)
from .price_volume_audits import build_feature_audits
from .price_volume_availability import (
    AvailabilityMode,
    validate_availability_mode,
)
from .price_volume_contracts import (
    FeatureValueAudit,
    PriceVolumeFeatureBuildResult,
    PriceVolumeFeatureRow,
    strict_point_in_time_audit_pass,
)
from .price_volume_input import (
    CanonicalResearchBar,
    deduplicate_listing_bars,
    materialize_canonical_records,
    parse_canonical_bar,
    resolve_trading_sessions,
)


def _unique_audit_reasons(
    audits: Mapping[str, FeatureValueAudit],
    *,
    limitations: bool,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            reason
            for audit in audits.values()
            for reason in (
                audit.research_limitation_reason_codes
                if limitations
                else audit.reason_codes
            )
        )
    )


def _latest_audit_timestamp(
    audits: Mapping[str, FeatureValueAudit],
    *,
    observed: bool,
) -> datetime | None:
    values = (
        audit.observed_available_at if observed else audit.available_at
        for audit in audits.values()
    )
    return max((value for value in values if value is not None), default=None)


def _build_feature_row(
    current: CanonicalResearchBar,
    audits: Mapping[str, FeatureValueAudit],
    availability_mode: AvailabilityMode,
    *,
    market: str,
) -> PriceVolumeFeatureRow:
    spec = price_volume_feature_spec(market)
    feature_values = {name: audits[name].value for name in PRICE_VOLUME_FEATURE_NAMES}
    missing = tuple(name for name, value in feature_values.items() if value is None)
    hard_reasons = _unique_audit_reasons(audits, limitations=False)
    limitations = _unique_audit_reasons(audits, limitations=True)
    return PriceVolumeFeatureRow(
        security_id=current.security_id,
        listing_period_id=current.listing_period_id,
        symbol=current.symbol,
        market=market,
        decision_date=current.trade_date,
        decision_at=current.decision_at,
        horizon=5,
        feature_schema_version=spec.schema_version,
        feature_schema_hash=spec.schema_hash,
        price_basis=PRICE_VOLUME_PRICE_BASIS,
        availability_mode=availability_mode,
        decision_close_price=current.values["close_price"],
        feature_values=feature_values,
        feature_audits=audits,
        latest_available_at=_latest_audit_timestamp(audits, observed=False),
        latest_observed_available_at=_latest_audit_timestamp(audits, observed=True),
        missing_features=missing,
        hard_fail_reason_codes=hard_reasons,
        research_limitation_reason_codes=limitations,
        point_in_time_audit_pass=strict_point_in_time_audit_pass(
            availability_mode,
            hard_reasons,
            limitations,
        ),
        hard_fail=bool(hard_reasons or missing),
    )


def build_price_volume_features(
    records: object,
    *,
    market: str,
    trading_sessions: Sequence[date] | None = None,
    availability_mode: AvailabilityMode = "STRICT_CANONICAL",
) -> PriceVolumeFeatureBuildResult:
    """Build auditable, research-only features without reading storage.

    ``trading_sessions`` should be a verified venue session sequence. When it is
    omitted, the union of input dates is used. Missing bars inside a supplied
    sequence fail the affected features rather than being silently skipped.

    ``RESEARCH_SCHEDULING_HINT`` must be explicit. It substitutes the frozen
    16:00 Taipei cutoff only for ``FIRST_OBSERVED_AT_RETRIEVAL`` rows, preserves
    observed timestamps and limitations, and can never promote output.
    """

    normalized_mode = validate_availability_mode(availability_mode)
    materialized = materialize_canonical_records(records)
    bars = tuple(
        parse_canonical_bar(
            record,
            availability_mode=normalized_mode,
            expected_market=market,
        )
        for record in materialized
    )
    sessions = resolve_trading_sessions(bars, trading_sessions)
    session_positions = {session: index for index, session in enumerate(sessions)}
    by_listing_period: dict[str, list[CanonicalResearchBar]] = {}
    for bar in bars:
        by_listing_period.setdefault(bar.listing_period_id, []).append(bar)

    rows: list[PriceVolumeFeatureRow] = []
    for listing_bars in by_listing_period.values():
        bars_by_date = deduplicate_listing_bars(listing_bars)
        for current in bars_by_date.values():
            audits = build_feature_audits(
                current=current,
                session_positions=session_positions,
                sessions=sessions,
                bars_by_date=bars_by_date,
            )
            rows.append(
                _build_feature_row(
                    current,
                    audits,
                    normalized_mode,
                    market=market,
                )
            )
    rows.sort(key=lambda row: (row.decision_date, row.symbol, row.listing_period_id))
    spec = price_volume_feature_spec(market)
    return PriceVolumeFeatureBuildResult(
        input_row_count=len(materialized),
        trading_sessions=sessions,
        rows=tuple(rows),
        market=market,
        availability_mode=normalized_mode,
        feature_schema_version=spec.schema_version,
        feature_schema_hash=spec.schema_hash,
    )


def build_twse_price_volume_features(
    records: object,
    *,
    trading_sessions: Sequence[date] | None = None,
    availability_mode: AvailabilityMode = "STRICT_CANONICAL",
) -> PriceVolumeFeatureBuildResult:
    """Build TWSE common-stock features with the legacy public API."""

    return build_price_volume_features(
        records,
        market="TWSE",
        trading_sessions=trading_sessions,
        availability_mode=availability_mode,
    )


__all__ = ["build_price_volume_features", "build_twse_price_volume_features"]
