"""Pure TWSE raw price/volume feature construction with fail-closed audits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from .twse_price_volume_audits import build_feature_audits
from .twse_price_volume_availability import (
    AvailabilityMode,
    validate_availability_mode,
)
from .twse_price_volume_contracts import (
    FeatureValueAudit,
    TwsePriceVolumeFeatureBuildResult,
    TwsePriceVolumeFeatureRow,
    strict_point_in_time_audit_pass,
)
from .twse_price_volume_input import (
    CanonicalResearchBar,
    deduplicate_listing_bars,
    materialize_canonical_records,
    parse_canonical_bar,
    resolve_trading_sessions,
)
from .twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
    TWSE_PRICE_VOLUME_PRICE_BASIS,
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
) -> TwsePriceVolumeFeatureRow:
    feature_values = {
        name: audits[name].value for name in TWSE_PRICE_VOLUME_FEATURE_NAMES
    }
    missing = tuple(name for name, value in feature_values.items() if value is None)
    hard_reasons = _unique_audit_reasons(audits, limitations=False)
    limitations = _unique_audit_reasons(audits, limitations=True)
    return TwsePriceVolumeFeatureRow(
        security_id=current.security_id,
        listing_period_id=current.listing_period_id,
        symbol=current.symbol,
        decision_date=current.trade_date,
        decision_at=current.decision_at,
        horizon=5,
        feature_schema_version=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        feature_schema_hash=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        price_basis=TWSE_PRICE_VOLUME_PRICE_BASIS,
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


def build_twse_price_volume_features(
    records: object,
    *,
    trading_sessions: Sequence[date] | None = None,
    availability_mode: AvailabilityMode = "STRICT_CANONICAL",
) -> TwsePriceVolumeFeatureBuildResult:
    """Build auditable, research-only features without reading storage.

    ``trading_sessions`` should be a verified TWSE session sequence. When it is
    omitted, the union of input dates is used. Missing bars inside a supplied
    sequence fail the affected features rather than being silently skipped.

    ``RESEARCH_SCHEDULING_HINT`` must be explicit. It substitutes the frozen
    16:00 Taipei cutoff only for ``FIRST_OBSERVED_AT_RETRIEVAL`` rows, preserves
    observed timestamps and limitations, and can never promote output.
    """

    normalized_mode = validate_availability_mode(availability_mode)
    materialized = materialize_canonical_records(records)
    bars = tuple(
        parse_canonical_bar(record, availability_mode=normalized_mode)
        for record in materialized
    )
    sessions = resolve_trading_sessions(bars, trading_sessions)
    session_positions = {session: index for index, session in enumerate(sessions)}
    by_listing_period: dict[str, list[CanonicalResearchBar]] = {}
    for bar in bars:
        by_listing_period.setdefault(bar.listing_period_id, []).append(bar)

    rows: list[TwsePriceVolumeFeatureRow] = []
    for listing_bars in by_listing_period.values():
        bars_by_date = deduplicate_listing_bars(listing_bars)
        for current in bars_by_date.values():
            audits = build_feature_audits(
                current=current,
                session_positions=session_positions,
                sessions=sessions,
                bars_by_date=bars_by_date,
            )
            rows.append(_build_feature_row(current, audits, normalized_mode))
    rows.sort(key=lambda row: (row.decision_date, row.symbol, row.listing_period_id))
    return TwsePriceVolumeFeatureBuildResult(
        input_row_count=len(materialized),
        trading_sessions=sessions,
        rows=tuple(rows),
        availability_mode=normalized_mode,
    )


__all__ = ["build_twse_price_volume_features"]
