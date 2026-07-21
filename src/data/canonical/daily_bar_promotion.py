"""Promote verified R2 bytes into traceable, still fail-closed canonical rows."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast, final

from src.data.archive.contracts import VerifiedHistoricalArchive

from .contracts import (
    CANONICAL_DAILY_BAR_SCHEMA_VERSION,
    CanonicalDailyBar,
    PromotionResult,
)
from .evidence_contracts import HistoricalDecisionContext
from .historical_security_resolver import HistoricalSecurityResolver


def _date_value(value: object) -> date | None:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _decimal(value: object, *, required: bool) -> Decimal | None:
    if value is None and not required:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _integer(value: object) -> int | None:
    if value is None:
        return None
    parsed = _decimal(value, required=False)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


@final
class CanonicalDailyBarPromotionService:
    """Create auditable research rows without upgrading raw evidence by assertion."""

    def __init__(
        self,
        resolver: HistoricalSecurityResolver,
        decision_contexts: Mapping[tuple[str, date], HistoricalDecisionContext],
    ) -> None:
        self._resolver = resolver
        self._decision_contexts = decision_contexts

    def promote(self, archive: VerifiedHistoricalArchive) -> PromotionResult:
        manifest = archive.manifest
        if (
            archive.content_sha256 != manifest.parquet_sha256
            or archive.byte_size != manifest.byte_size
            or archive.row_count != manifest.row_count
            or archive.schema_version != manifest.schema_version
            or len(archive.rows) != manifest.row_count
        ):
            raise ValueError("verified archive contract is internally inconsistent")
        rows: list[CanonicalDailyBar] = []
        reasons: Counter[str] = Counter()
        rejected = 0
        for raw in archive.rows:
            built, row_reasons = self._promote_row(raw, archive)
            reasons.update(row_reasons)
            if built is None:
                rejected += 1
            else:
                rows.append(built)
        return PromotionResult(
            source_row_count=manifest.row_count,
            canonical_rows=tuple(rows),
            rejected_row_count=rejected,
            reason_counts=tuple(sorted(reasons.items())),
        )

    def _promote_row(
        self,
        raw: Mapping[str, object],
        archive: VerifiedHistoricalArchive,
    ) -> tuple[CanonicalDailyBar | None, tuple[str, ...]]:
        manifest = archive.manifest
        trade_date = _date_value(raw.get("trade_date"))
        symbol = _text(raw.get("source_symbol"))
        if raw.get("parse_status") != "PARSED" or trade_date is None or symbol is None:
            return None, ("RAW_ROW_NOT_PARSEABLE",)
        if symbol != manifest.source_symbol:
            return None, ("RAW_SYMBOL_MANIFEST_MISMATCH",)
        context = self._decision_contexts.get((manifest.scheduled_market, trade_date))
        if context is None:
            return None, ("DECISION_CONTEXT_UNAVAILABLE",)
        if (
            context.market != manifest.scheduled_market
            or context.trade_date != trade_date
        ):
            return None, ("DECISION_CONTEXT_IDENTITY_MISMATCH",)
        resolution = self._resolver.resolve(
            source_symbol=symbol,
            scheduled_market=manifest.scheduled_market,
            trade_date=trade_date,
            decision_at=context.decision_at,
        )
        if resolution.identity is None:
            return None, resolution.reason_codes
        identity = resolution.identity
        if identity.security_id is None:
            return None, ("HISTORICAL_IDENTITY_UNRESOLVED",)

        prices = tuple(
            _decimal(raw.get(field), required=True)
            for field in ("open_price", "high_price", "low_price", "close_price")
        )
        if any(value is None for value in prices):
            return None, ("CANONICAL_OHLC_INVALID",)
        open_price, high_price, low_price, close_price = cast(
            tuple[Decimal, Decimal, Decimal, Decimal], prices
        )
        raw_available_at = _datetime_value(raw.get("available_at"))
        raw_first_observed_at = _datetime_value(raw.get("first_observed_at"))
        raw_available_at_basis = _text(raw.get("available_at_basis"))
        source_revision_hash = _text(raw.get("source_revision_hash"))
        source_payload_hash = _text(raw.get("source_payload_hash"))
        if (
            raw_available_at is None
            or raw_first_observed_at is None
            or raw_available_at_basis is None
            or source_revision_hash is None
            or source_payload_hash is None
        ):
            return None, ("RAW_LINEAGE_INCOMPLETE",)

        row_reasons = list(resolution.reason_codes)
        if manifest.point_in_time_status != "VERIFIED":
            row_reasons.append("RAW_POINT_IN_TIME_UNVERIFIED")
        if raw.get("point_in_time_status") != "VERIFIED":
            row_reasons.append("ROW_POINT_IN_TIME_UNVERIFIED")
        if raw_available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL":
            row_reasons.append("RAW_AVAILABLE_AT_FIRST_OBSERVED_ONLY")
        if context.calendar_status != "VERIFIED":
            row_reasons.append("TRADING_CALENDAR_UNVERIFIED")
        if context.company_action_coverage_status != "VERIFIED":
            row_reasons.append("COMPANY_ACTION_COVERAGE_UNVERIFIED")
        if raw_available_at > context.decision_at:
            row_reasons.append("BAR_AVAILABLE_AFTER_DECISION")
        row_reasons = sorted(set(row_reasons))
        production_eligible = not row_reasons
        trading_volume = _decimal(raw.get("trading_volume"), required=False)
        trading_value = _decimal(raw.get("trading_value"), required=False)
        trade_count = _integer(raw.get("trade_count"))
        lineage: dict[str, object] = {
            "schema_version": CANONICAL_DAILY_BAR_SCHEMA_VERSION,
            "listing_period_id": identity.listing_period_id,
            "security_id": identity.security_id,
            "market": identity.market,
            "symbol": symbol,
            "trade_date": trade_date,
            "decision_at": context.decision_at,
            "open_price": open_price,
            "high_price": high_price,
            "low_price": low_price,
            "close_price": close_price,
            "trading_volume": trading_volume,
            "trading_value": trading_value,
            "trade_count": trade_count,
            "raw_archive_key": manifest.archive_key,
            "raw_object_key": manifest.object_key,
            "raw_parquet_sha256": archive.content_sha256,
            "raw_source_revision_hash": source_revision_hash,
            "raw_source_payload_hash": source_payload_hash,
            "raw_first_observed_at": raw_first_observed_at,
            "raw_available_at": raw_available_at,
            "raw_available_at_basis": raw_available_at_basis,
            "identity_revision_hash": identity.source_revision_hash,
            "publication_rule_version": context.publication_rule_version,
            "calendar_revision_hash": context.calendar_revision_hash,
            "calendar_available_at": context.calendar_available_at,
            "company_action_revision_hash": context.company_action_revision_hash,
            "company_action_available_at": context.company_action_available_at,
            "point_in_time_status": "VERIFIED" if production_eligible else "UNVERIFIED",
            "usage_scope": "MODEL_ELIGIBLE" if production_eligible else "RESEARCH_ONLY",
            "system_status": "PASS" if production_eligible else "RESEARCH_ONLY",
            "production_eligible": production_eligible,
            "reason_codes": tuple(row_reasons),
        }
        return (
            CanonicalDailyBar(
                schema_version=CANONICAL_DAILY_BAR_SCHEMA_VERSION,
                listing_period_id=identity.listing_period_id,
                security_id=identity.security_id,
                market=identity.market,
                symbol=symbol,
                trade_date=trade_date,
                decision_at=context.decision_at,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                trading_volume=trading_volume,
                trading_value=trading_value,
                trade_count=trade_count,
                raw_archive_key=manifest.archive_key,
                raw_object_key=manifest.object_key,
                raw_parquet_sha256=archive.content_sha256,
                raw_source_revision_hash=source_revision_hash,
                raw_source_payload_hash=source_payload_hash,
                raw_first_observed_at=raw_first_observed_at,
                raw_available_at=raw_available_at,
                raw_available_at_basis=raw_available_at_basis,
                identity_revision_hash=identity.source_revision_hash,
                publication_rule_version=context.publication_rule_version,
                calendar_revision_hash=context.calendar_revision_hash,
                calendar_available_at=context.calendar_available_at,
                company_action_revision_hash=context.company_action_revision_hash,
                company_action_available_at=context.company_action_available_at,
                point_in_time_status=(
                    "VERIFIED" if production_eligible else "UNVERIFIED"
                ),
                usage_scope=(
                    "MODEL_ELIGIBLE" if production_eligible else "RESEARCH_ONLY"
                ),
                system_status="PASS" if production_eligible else "RESEARCH_ONLY",
                production_eligible=production_eligible,
                reason_codes=tuple(row_reasons),
                canonical_row_hash=CanonicalDailyBar.content_hash(lineage),
            ),
            tuple(row_reasons),
        )
