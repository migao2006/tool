"""Read append-only listing evidence through a private Supabase adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from types import MappingProxyType
from typing import Protocol, cast, final

from .evidence_contracts import ListingPeriodIdentity


_FIELDS = (
    "listing_evidence_id",
    "listing_period_id",
    "security_id",
    "listing_market",
    "asset_type",
    "isin",
    "source_symbol",
    "effective_from",
    "effective_to",
    "identity_resolution_status",
    "source_id",
    "source_dataset",
    "source_version",
    "source_revision_hash",
    "source_payload_hash",
    "first_observed_at",
    "available_at",
    "available_at_basis",
    "usage_scope",
    "system_status",
    "reason_codes",
)


@final
class PointInTimeEvidenceReadError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


class ListingEvidenceRowSource(Protocol):
    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...


def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {field}")
    return value.strip()


def _positive_integer(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"invalid {field}")
    return value


def _optional_positive_integer(row: Mapping[str, object], field: str) -> int | None:
    value = row.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"invalid {field}")
    return value


def _date(row: Mapping[str, object], field: str, *, required: bool) -> date | None:
    value = row.get(field)
    if value is None and not required:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"invalid {field}") from error


def _datetime(row: Mapping[str, object], field: str) -> datetime:
    value = row.get(field)
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except ValueError as error:
        raise ValueError(f"invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timezone-naive {field}")
    return parsed.astimezone(timezone.utc)


def _reasons(row: Mapping[str, object]) -> tuple[str, ...]:
    value = row.get("reason_codes")
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid reason_codes")
    raw = cast(Sequence[object], value)
    if any(not isinstance(item, str) or not item for item in raw):
        raise ValueError("invalid reason_codes")
    return tuple(cast(str, item) for item in raw)


def _identity(row: Mapping[str, object]) -> ListingPeriodIdentity:
    resolution_status = _text(row, "identity_resolution_status")
    system_status = _text(row, "system_status")
    point_in_time_status = (
        "VERIFIED"
        if resolution_status == "VERIFIED" and system_status == "PASS"
        else "UNVERIFIED"
    )
    effective_from = _date(row, "effective_from", required=True)
    assert effective_from is not None
    return ListingPeriodIdentity(
        listing_period_id=_text(row, "listing_period_id"),
        security_id=_optional_positive_integer(row, "security_id"),
        isin=None if row.get("isin") is None else _text(row, "isin"),
        market=_text(row, "listing_market"),
        source_symbol=_text(row, "source_symbol"),
        asset_type=_text(row, "asset_type"),
        effective_from=effective_from,
        effective_to=_date(row, "effective_to", required=False),
        available_at=_datetime(row, "available_at"),
        first_observed_at=_datetime(row, "first_observed_at"),
        source_id=_positive_integer(row, "source_id"),
        source_dataset=_text(row, "source_dataset"),
        source_version=_text(row, "source_version"),
        source_revision_hash=_text(row, "source_revision_hash"),
        source_payload_hash=_text(row, "source_payload_hash"),
        resolution_status=resolution_status,
        available_at_basis=_text(row, "available_at_basis"),
        point_in_time_status=point_in_time_status,
        usage_scope=_text(row, "usage_scope"),
        system_status=system_status,
        reason_codes=_reasons(row),
    )


@dataclass(frozen=True)
class ListingPeriodEvidenceSnapshot:
    identities: tuple[ListingPeriodIdentity, ...]
    snapshot_sha256: str
    decision_at: datetime
    complete: bool


@final
class ListingPeriodEvidenceRepository:
    """Keyset-page every evidence row known by one decision timestamp."""

    def __init__(
        self, source: ListingEvidenceRowSource, *, page_size: int = 500
    ) -> None:
        if not 1 <= page_size <= 1_000:
            raise ValueError("page_size must be between 1 and 1000")
        self._source = source
        self._page_size = page_size

    def fetch(
        self,
        *,
        decision_at: datetime,
        asset_type: str = "COMMON_STOCK",
        market: str | None = None,
        max_rows: int | None = None,
    ) -> ListingPeriodEvidenceSnapshot:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("decision_at must be timezone-aware")
        if asset_type not in {"COMMON_STOCK", "ETF"}:
            raise ValueError("unsupported asset_type")
        if market not in {None, "TWSE", "TPEX"}:
            raise ValueError("unsupported market")
        if max_rows is not None and max_rows <= 0:
            raise ValueError("max_rows must be positive")

        cutoff = decision_at.astimezone(timezone.utc)
        identities: list[ListingPeriodIdentity] = []
        hashes: list[str] = []
        last_evidence_id = 0
        complete = True
        while True:
            remaining = None if max_rows is None else max_rows - len(identities)
            if remaining is not None and remaining <= 0:
                complete = False
                break
            request_limit = (
                self._page_size
                if remaining is None
                else min(self._page_size, remaining)
            )
            filters = {
                "listing_evidence_id": f"gt.{last_evidence_id}",
                "available_at": f"lte.{cutoff.isoformat()}",
                "asset_type": f"eq.{asset_type}",
                "order": "listing_evidence_id.asc",
            }
            if market is not None:
                filters["listing_market"] = f"eq.{market}"
            page = self._source.select_rows(
                "security_listing_periods",
                select=",".join(_FIELDS),
                filters=filters,
                limit=request_limit,
            )
            if len(page) > request_limit:
                raise PointInTimeEvidenceReadError(
                    "LISTING_EVIDENCE_PAGE_INVALID",
                    "Supabase returned more listing rows than requested",
                )
            if not page:
                break
            for raw in page:
                try:
                    current_id = _positive_integer(raw, "listing_evidence_id")
                    if current_id <= last_evidence_id:
                        raise ValueError("listing rows are not strictly ordered")
                    raw_available_at = _datetime(raw, "available_at")
                    if raw_available_at > cutoff:
                        raise PointInTimeEvidenceReadError(
                            "LISTING_EVIDENCE_FUTURE_ROW",
                            "Supabase returned listing evidence after the decision cutoff",
                        )
                    identity = _identity(MappingProxyType(dict(raw)))
                except PointInTimeEvidenceReadError:
                    raise
                except (TypeError, ValueError) as error:
                    raise PointInTimeEvidenceReadError(
                        "LISTING_EVIDENCE_INVALID",
                        "Listing-period evidence is incomplete or inconsistent",
                    ) from error
                last_evidence_id = current_id
                identities.append(identity)
                hashes.append(
                    "\0".join(
                        (
                            str(current_id),
                            identity.source_revision_hash,
                            identity.available_at.isoformat(),
                            identity.resolution_status,
                        )
                    )
                )
            if len(page) < request_limit:
                break
        return ListingPeriodEvidenceSnapshot(
            identities=tuple(identities),
            snapshot_sha256=sha256("\n".join(hashes).encode()).hexdigest(),
            decision_at=cutoff,
            complete=complete,
        )
