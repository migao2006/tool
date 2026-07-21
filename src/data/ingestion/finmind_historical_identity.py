"""Read verified listing identities for FinMind historical evidence rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol

from .contracts import IngestionError
from .finmind_historical_evidence_contracts import HistoricalEvidenceIdentity


IDENTITY_PAGE_SIZE = 1_000


class HistoricalIdentitySource(Protocol):
    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...


def positive_database_id(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise IngestionError(
            "HISTORICAL_IDENTITY_ROW_INVALID", f"{field} must be a positive integer"
        )
    try:
        parsed = int(str(value))
    except ValueError as error:
        raise IngestionError(
            "HISTORICAL_IDENTITY_ROW_INVALID", f"{field} must be a positive integer"
        ) from error
    if parsed <= 0:
        raise IngestionError(
            "HISTORICAL_IDENTITY_ROW_INVALID", f"{field} must be a positive integer"
        )
    return parsed


def _date_value(value: object, field: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise IngestionError(
            "HISTORICAL_IDENTITY_ROW_INVALID", f"{field} must use YYYY-MM-DD"
        ) from error


def _datetime_value(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise IngestionError(
            "HISTORICAL_IDENTITY_ROW_INVALID",
            "identity available_at must be an ISO timestamp",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IngestionError(
            "HISTORICAL_IDENTITY_ROW_INVALID",
            "identity available_at must be timezone-aware",
        )
    return parsed


def _identity_from_row(row: Mapping[str, object]) -> HistoricalEvidenceIdentity:
    effective_from = _date_value(row.get("effective_from"), "effective_from")
    if effective_from is None:
        raise IngestionError(
            "HISTORICAL_IDENTITY_ROW_INVALID", "effective_from is required"
        )
    return HistoricalEvidenceIdentity(
        listing_evidence_id=positive_database_id(
            row.get("listing_evidence_id"), "listing_evidence_id"
        ),
        listing_period_id=str(row.get("listing_period_id") or ""),
        security_id=positive_database_id(row.get("security_id"), "security_id"),
        source_symbol=str(row.get("source_symbol") or ""),
        effective_from=effective_from,
        effective_to=_date_value(row.get("effective_to"), "effective_to"),
        available_at=_datetime_value(row.get("available_at")),
        market=str(row.get("listing_market") or ""),
        asset_type=str(row.get("asset_type") or ""),
    )


def _load_verified_twse_identities(
    source: HistoricalIdentitySource,
    *,
    symbols: Sequence[str] | None,
) -> tuple[HistoricalEvidenceIdentity, ...]:
    """Page through append-only PASS identities for the explicit symbol set."""

    rows: list[dict[str, object]] = []
    offset = 0
    while True:
        filters = {
            "listing_market": "eq.TWSE",
            "asset_type": "eq.COMMON_STOCK",
            "identity_resolution_status": "eq.VERIFIED",
            "usage_scope": "eq.POINT_IN_TIME_IDENTITY",
            "system_status": "eq.PASS",
            "order": "listing_evidence_id.asc",
            "offset": str(offset),
        }
        if symbols is not None:
            filters["source_symbol"] = f"in.({','.join(symbols)})"
        page = source.select_rows(
            "security_listing_periods",
            select=(
                "listing_evidence_id,listing_period_id,security_id,"
                "listing_market,asset_type,source_symbol,effective_from,"
                "effective_to,available_at"
            ),
            filters=filters,
            limit=IDENTITY_PAGE_SIZE,
        )
        rows.extend(page)
        if len(page) < IDENTITY_PAGE_SIZE:
            break
        offset += IDENTITY_PAGE_SIZE
    return tuple(_identity_from_row(row) for row in rows)


def load_verified_twse_identities(
    source: HistoricalIdentitySource,
    *,
    symbols: Sequence[str],
) -> tuple[HistoricalEvidenceIdentity, ...]:
    """Load verified identities for an explicit non-empty symbol batch."""

    if not symbols:
        raise IngestionError(
            "HISTORICAL_IDENTITY_SYMBOLS_REQUIRED",
            "identity lookup requires at least one symbol",
        )
    return _load_verified_twse_identities(source, symbols=symbols)


def load_all_verified_twse_identities(
    source: HistoricalIdentitySource,
) -> tuple[HistoricalEvidenceIdentity, ...]:
    """Page through the complete verified TWSE common-stock identity catalog."""

    return _load_verified_twse_identities(source, symbols=None)
