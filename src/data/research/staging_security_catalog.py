"""Deterministic security identity bridge for isolated research staging."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from hashlib import sha256
import json
from typing import Protocol, cast

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.returned_ids import returned_id_map, returned_security_id_map


CATALOG_SCHEMA_VERSION = "research-security-catalog.v1"
SUPPORTED_MARKETS = frozenset({"TWSE", "TPEX"})
ASSET_TYPE = "COMMON_STOCK"
SYSTEM_STATUS = "RESEARCH_ONLY"
_SOURCE_FIELDS = frozenset(
    {
        "source_code",
        "display_name",
        "source_timezone",
        "revision_policy",
        "is_active",
    }
)
_SECURITY_FIELDS = frozenset(
    {
        "symbol",
        "display_name",
        "market",
        "asset_type",
        "currency",
        "listing_date",
        "delisting_date",
        "isin",
        "source_code",
    }
)
_CATALOG_FIELDS = frozenset(
    {
        "schema_version",
        "market",
        "asset_type",
        "row_count",
        "sources",
        "securities",
        "system_status",
        "catalog_sha256",
    }
)


class ResearchSecurityCatalogWriter(Protocol):
    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        page_size: int = 1_000,
        max_rows: int = 10_000,
    ) -> list[dict[str, object]]: ...

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]: ...


def _fail(reason_code: str, message: str) -> IngestionError:
    return IngestionError(reason_code, message)


def _market(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in SUPPORTED_MARKETS:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_SCOPE_INVALID",
            "Research security catalog market is unsupported",
        )
    return normalized


def _required_text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            f"Research security catalog field is invalid: {field}",
        )
    return value.strip()


def _optional_text(row: Mapping[str, object], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            f"Research security catalog field is invalid: {field}",
        )
    return value.strip()


def _positive_id(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            f"Research security catalog identifier is invalid: {field}",
        )
    try:
        parsed = int(value)
    except ValueError as error:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            f"Research security catalog identifier is invalid: {field}",
        ) from error
    if parsed <= 0:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            f"Research security catalog identifier is invalid: {field}",
        )
    return parsed


def _canonical_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _source_row(row: Mapping[str, object]) -> dict[str, object]:
    if set(row) != _SOURCE_FIELDS:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security source fields do not match the catalog contract",
        )
    is_active = row.get("is_active")
    if not isinstance(is_active, bool):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security source active state is invalid",
        )
    timezone = _required_text(row, "source_timezone")
    if timezone != "Asia/Taipei":
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security source timezone is invalid",
        )
    return {
        "source_code": _required_text(row, "source_code"),
        "display_name": _required_text(row, "display_name"),
        "source_timezone": timezone,
        "revision_policy": _required_text(row, "revision_policy"),
        "is_active": is_active,
    }


def _security_row(
    row: Mapping[str, object],
    *,
    market: str,
) -> dict[str, object]:
    if set(row) != _SECURITY_FIELDS:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security fields do not match the catalog contract",
        )
    symbol = _required_text(row, "symbol")
    row_market = _required_text(row, "market")
    asset_type = _required_text(row, "asset_type")
    currency = _required_text(row, "currency")
    listing_date = _optional_text(row, "listing_date")
    delisting_date = _optional_text(row, "delisting_date")
    if (
        row_market != market
        or asset_type != ASSET_TYPE
        or currency != "TWD"
        or len(symbol) != 4
        or not symbol.isdigit()
        or symbol.startswith("91")
    ):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_SCOPE_MISMATCH",
            "Research security row is outside the requested venue or asset scope",
        )
    try:
        parsed_listing = date.fromisoformat(listing_date) if listing_date else None
        parsed_delisting = date.fromisoformat(delisting_date) if delisting_date else None
    except ValueError as error:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security listing interval is invalid",
        ) from error
    if (
        parsed_listing is not None
        and parsed_delisting is not None
        and parsed_delisting < parsed_listing
    ):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security listing interval is invalid",
        )
    return {
        "symbol": symbol,
        "display_name": _required_text(row, "display_name"),
        "market": row_market,
        "asset_type": asset_type,
        "currency": currency,
        "listing_date": listing_date,
        "delisting_date": delisting_date,
        "isin": _optional_text(row, "isin"),
        "source_code": _required_text(row, "source_code"),
    }


def _catalog_content(
    *,
    market: str,
    sources: Sequence[Mapping[str, object]],
    securities: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    normalized_sources = sorted(
        (_source_row(row) for row in sources),
        key=lambda row: cast(str, row["source_code"]),
    )
    normalized_securities = sorted(
        (_security_row(row, market=market) for row in securities),
        key=lambda row: cast(str, row["symbol"]),
    )
    source_codes = [cast(str, row["source_code"]) for row in normalized_sources]
    symbols = [cast(str, row["symbol"]) for row in normalized_securities]
    referenced_sources = {
        cast(str, row["source_code"]) for row in normalized_securities
    }
    if (
        not normalized_sources
        or not normalized_securities
        or len(source_codes) != len(set(source_codes))
        or len(symbols) != len(set(symbols))
        or referenced_sources != set(source_codes)
    ):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security catalog coverage or uniqueness is invalid",
        )
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "market": market,
        "asset_type": ASSET_TYPE,
        "row_count": len(normalized_securities),
        "sources": normalized_sources,
        "securities": normalized_securities,
        "system_status": SYSTEM_STATUS,
    }


def export_research_security_catalog(
    writer: ResearchSecurityCatalogWriter,
    *,
    market: str,
) -> dict[str, object]:
    """Export business identity only; database-generated IDs never cross environments."""

    normalized_market = _market(market)
    selected_securities = writer.select_all_rows(
        "securities",
        select=(
            "symbol,display_name,market,asset_type,currency,"
            "listing_date,delisting_date,isin,source_id"
        ),
        filters={
            "market": f"eq.{normalized_market}",
            "asset_type": f"eq.{ASSET_TYPE}",
            "order": "symbol.asc",
        },
        page_size=1_000,
        max_rows=5_000,
    )
    source_ids = {_positive_id(row, "source_id") for row in selected_securities}
    selected_sources = writer.select_all_rows(
        "data_sources",
        select=(
            "source_id,source_code,display_name,source_timezone,"
            "revision_policy,is_active"
        ),
        filters={"order": "source_code.asc"},
        page_size=100,
        max_rows=1_000,
    )
    source_by_id = {
        _positive_id(row, "source_id"): {
            "source_code": _required_text(row, "source_code"),
            "display_name": _required_text(row, "display_name"),
            "source_timezone": _required_text(row, "source_timezone"),
            "revision_policy": _required_text(row, "revision_policy"),
            "is_active": row.get("is_active"),
        }
        for row in selected_sources
        if _positive_id(row, "source_id") in source_ids
    }
    if set(source_by_id) != source_ids:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_SOURCE_MISSING",
            "A production research security source could not be resolved",
        )
    securities = [
        {
            "symbol": _required_text(row, "symbol"),
            "display_name": _required_text(row, "display_name"),
            "market": _required_text(row, "market"),
            "asset_type": _required_text(row, "asset_type"),
            "currency": _required_text(row, "currency"),
            "listing_date": _optional_text(row, "listing_date"),
            "delisting_date": _optional_text(row, "delisting_date"),
            "isin": _optional_text(row, "isin"),
            "source_code": source_by_id[_positive_id(row, "source_id")][
                "source_code"
            ],
        }
        for row in selected_securities
    ]
    content = _catalog_content(
        market=normalized_market,
        sources=list(source_by_id.values()),
        securities=securities,
    )
    return {**content, "catalog_sha256": _canonical_hash(content)}


def validate_research_security_catalog(
    payload: Mapping[str, object],
    *,
    market: str,
) -> dict[str, object]:
    normalized_market = _market(market)
    if set(payload) != _CATALOG_FIELDS:
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security catalog fields do not match the contract",
        )
    if (
        payload.get("schema_version") != CATALOG_SCHEMA_VERSION
        or payload.get("market") != normalized_market
        or payload.get("asset_type") != ASSET_TYPE
        or payload.get("system_status") != SYSTEM_STATUS
    ):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_SCOPE_MISMATCH",
            "Research security catalog scope does not match the staging job",
        )
    raw_sources = payload.get("sources")
    raw_securities = payload.get("securities")
    if not isinstance(raw_sources, list) or not isinstance(raw_securities, list):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security catalog row collections are invalid",
        )
    content = _catalog_content(
        market=normalized_market,
        sources=[
            cast(Mapping[str, object], row)
            for row in raw_sources
            if isinstance(row, Mapping)
        ],
        securities=[
            cast(Mapping[str, object], row)
            for row in raw_securities
            if isinstance(row, Mapping)
        ],
    )
    if len(raw_sources) != len(cast(list[object], content["sources"])) or len(
        raw_securities
    ) != len(cast(list[object], content["securities"])):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security catalog contains invalid rows",
        )
    raw_count = payload.get("row_count")
    if (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or raw_count != content["row_count"]
    ):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security catalog row count is invalid",
        )
    stored_hash = str(payload.get("catalog_sha256") or "").strip().lower()
    if stored_hash != _canonical_hash(content):
        raise _fail(
            "RESEARCH_SECURITY_CATALOG_HASH_MISMATCH",
            "Research security catalog hash does not match its content",
        )
    return {**content, "catalog_sha256": stored_hash}


def sync_research_security_catalog(
    writer: ResearchSecurityCatalogWriter,
    payload: Mapping[str, object],
    *,
    market: str,
) -> dict[str, object]:
    """Resolve environment-local IDs and fail closed on any incomplete staging write."""

    catalog = validate_research_security_catalog(payload, market=market)
    sources = cast(list[dict[str, object]], catalog["sources"])
    returned_sources = writer.upsert(
        "data_sources",
        sources,
        on_conflict="source_code",
        select=(
            "source_id,source_code,display_name,source_timezone,"
            "revision_policy,is_active"
        ),
        return_rows=True,
    )
    source_ids = returned_id_map(
        returned_sources,
        code_key="source_code",
        id_key="source_id",
    )
    required_sources = {cast(str, row["source_code"]) for row in sources}
    if set(source_ids) != required_sources or any(
        source_id <= 0 for source_id in source_ids.values()
    ):
        raise _fail(
            "RESEARCH_SECURITY_SOURCE_SYNC_INCOMPLETE",
            "Staging did not return every research security data source",
        )
    expected_sources = {
        cast(str, row["source_code"]): row
        for row in sources
    }
    for row in returned_sources:
        source_code = str(row.get("source_code") or "").strip()
        expected_source = expected_sources.get(source_code)
        if expected_source is None or any(
            row.get(field) != expected_source[field]
            for field in (
                "source_code",
                "display_name",
                "source_timezone",
                "revision_policy",
                "is_active",
            )
        ):
            raise _fail(
                "RESEARCH_SECURITY_SOURCE_SYNC_MISMATCH",
                "Staging research security source differs from the catalog",
            )
    securities = [
        {
            key: value
            for key, value in row.items()
            if key != "source_code"
        }
        | {"source_id": source_ids[cast(str, row["source_code"])]}
        for row in cast(list[dict[str, object]], catalog["securities"])
    ]
    returned_securities = writer.upsert(
        "securities",
        securities,
        on_conflict="market,symbol",
        select=(
            "security_id,symbol,display_name,market,asset_type,currency,"
            "listing_date,delisting_date,isin,source_id"
        ),
        return_rows=True,
    )
    returned_ids = returned_security_id_map(returned_securities)
    expected = {
        (cast(str, row["market"]), cast(str, row["symbol"])) for row in securities
    }
    if set(returned_ids) != expected or any(
        security_id <= 0 for security_id in returned_ids.values()
    ):
        raise _fail(
            "RESEARCH_SECURITY_SYNC_INCOMPLETE",
            "Staging did not return every research security identity",
        )
    expected_by_key = {
        (cast(str, row["market"]), cast(str, row["symbol"])): row
        for row in securities
    }
    for row in returned_securities:
        key = (
            str(row.get("market") or "").strip(),
            str(row.get("symbol") or "").strip(),
        )
        expected_row = expected_by_key.get(key)
        if expected_row is None or any(
            row.get(field) != expected_row[field]
            for field in (
                "symbol",
                "display_name",
                "market",
                "asset_type",
                "currency",
                "listing_date",
                "delisting_date",
                "isin",
                "source_id",
            )
        ):
            raise _fail(
                "RESEARCH_SECURITY_SYNC_MISMATCH",
                "Staging research security identity differs from the catalog",
            )
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "market": catalog["market"],
        "asset_type": ASSET_TYPE,
        "row_count": catalog["row_count"],
        "catalog_sha256": catalog["catalog_sha256"],
        "system_status": SYSTEM_STATUS,
        "status": "PASS",
    }
