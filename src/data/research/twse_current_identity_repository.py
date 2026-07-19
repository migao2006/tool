"""Read a bounded current-identity snapshot from private Supabase tables."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol, final

from .twse_archive_feature_contracts import (
    TwseCurrentSecurityIdentity,
    TwseIdentitySnapshot,
    identity_snapshot_hash,
)


class SecurityRowSource(Protocol):
    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("security_id is invalid")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is invalid")
    return value.strip()


def _date(value: object, field_name: str, *, optional: bool) -> date | None:
    if value is None and optional:
        return None
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{field_name} is invalid") from error


@final
class TwseCurrentIdentityRepository:
    """Keyset-page ``securities`` without claiming point-in-time identity."""

    def __init__(self, source: SecurityRowSource, *, page_size: int = 500) -> None:
        if not 1 <= page_size <= 1_000:
            raise ValueError("page_size must be between 1 and 1000")
        self.source = source
        self.page_size = page_size

    def fetch(self) -> TwseIdentitySnapshot:
        last_security_id = 0
        identities: dict[str, TwseCurrentSecurityIdentity] = {}
        while True:
            page = self.source.select_rows(
                "securities",
                select=(
                    "security_id,symbol,market,asset_type,listing_date,delisting_date"
                ),
                filters={
                    "market": "eq.TWSE",
                    "asset_type": "eq.COMMON_STOCK",
                    "security_id": f"gt.{last_security_id}",
                    "order": "security_id.asc",
                },
                limit=self.page_size,
            )
            if len(page) > self.page_size:
                raise ValueError("Supabase returned too many current identities")
            if not page:
                break
            for row in page:
                security_id = _positive_integer(row.get("security_id"))
                if security_id <= last_security_id:
                    raise ValueError("current identities are not strictly ordered")
                identity = TwseCurrentSecurityIdentity(
                    security_id=security_id,
                    symbol=_text(row.get("symbol"), "symbol"),
                    market=_text(row.get("market"), "market"),
                    asset_type=_text(row.get("asset_type"), "asset_type"),
                    listing_date=_date(
                        row.get("listing_date"),
                        "listing_date",
                        optional=True,
                    ),
                    delisting_date=_date(
                        row.get("delisting_date"),
                        "delisting_date",
                        optional=True,
                    ),
                )
                if identity.symbol in identities:
                    raise ValueError(
                        "current identity snapshot contains a duplicate symbol"
                    )
                identities[identity.symbol] = identity
                last_security_id = security_id
            if len(page) < self.page_size:
                break
        return TwseIdentitySnapshot(
            by_symbol=identities,
            snapshot_sha256=identity_snapshot_hash(identities),
        )


__all__ = ["SecurityRowSource", "TwseCurrentIdentityRepository"]
