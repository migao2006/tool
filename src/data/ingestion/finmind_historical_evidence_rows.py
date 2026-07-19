"""Row parsing and lineage primitives for FinMind historical evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import cast
from zoneinfo import ZoneInfo

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .finmind_historical_evidence_contracts import HistoricalEvidenceIdentity
from .normalizers import revision_version


SUPPORTED_DATASETS = frozenset(
    {"dividend_results", "stock_splits", "par_value_changes", "suspended"}
)
COMMON_STOCK_SYMBOL = re.compile(r"^[1-9][0-9]{3}$")
TAIPEI = ZoneInfo("Asia/Taipei")
BASE_ACTION_REASONS = (
    "FINMIND_HISTORICAL_VINTAGE_UNAVAILABLE",
    "OFFICIAL_PUBLICATION_TIME_UNAVAILABLE",
    "FIRST_OBSERVED_AT_RETRIEVAL",
    "COMPLETE_ACTION_COVERAGE_NOT_ESTABLISHED",
)
BASE_STATE_REASONS = (
    "FINMIND_HISTORICAL_VINTAGE_UNAVAILABLE",
    "OFFICIAL_PUBLICATION_TIME_UNAVAILABLE",
    "FIRST_OBSERVED_AT_RETRIEVAL",
    "PARTIAL_SECURITY_STATE_EVENT_ONLY",
    "COMPLETE_SECURITY_STATE_SNAPSHOT_UNAVAILABLE",
)


def validate_twse_common_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in symbols)
    if not normalized:
        raise IngestionError(
            "FINMIND_HISTORICAL_SYMBOLS_REQUIRED",
            "at least one explicit TWSE common-stock symbol is required",
        )
    if len(set(normalized)) != len(normalized):
        raise IngestionError(
            "FINMIND_HISTORICAL_DUPLICATE_SYMBOL",
            "requested symbols must be unique",
        )
    if any(
        not COMMON_STOCK_SYMBOL.fullmatch(symbol) or symbol.startswith("91")
        for symbol in normalized
    ):
        raise IngestionError(
            "FINMIND_HISTORICAL_SYMBOL_UNSUPPORTED",
            "only four-digit TWSE common-stock symbols are supported",
        )
    return normalized


def records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    if payload.provider != "FINMIND" or payload.dataset not in SUPPORTED_DATASETS:
        raise IngestionError(
            "FINMIND_HISTORICAL_PAYLOAD_UNSUPPORTED",
            "historical evidence requires a supported FinMind payload",
        )
    if "token=" in payload.source_url.casefold():
        raise IngestionError(
            "FINMIND_SOURCE_URL_CONTAINS_CREDENTIAL",
            "FinMind source URL must not contain a token",
        )
    body = cast(object, payload.payload)
    if not isinstance(body, Mapping):
        raise IngestionError(
            "FINMIND_HISTORICAL_PAYLOAD_INVALID",
            "FinMind historical payload must contain a data array",
        )
    body_mapping = cast(Mapping[str, object], body)
    if not isinstance(body_mapping.get("data"), list):
        raise IngestionError(
            "FINMIND_HISTORICAL_PAYLOAD_INVALID",
            "FinMind historical payload must contain a data array",
        )
    rows = cast(list[object], body_mapping["data"])
    if not all(isinstance(row, Mapping) for row in rows):
        raise IngestionError(
            "FINMIND_HISTORICAL_ROW_INVALID",
            "every FinMind historical row must be an object",
        )
    return [cast(Mapping[str, object], row) for row in rows]


def event_date(row: Mapping[str, object]) -> date:
    raw = row.get("date")
    if not isinstance(raw, str):
        raise IngestionError(
            "FINMIND_HISTORICAL_DATE_INVALID", "historical row requires date"
        )
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise IngestionError(
            "FINMIND_HISTORICAL_DATE_INVALID", "historical date must be YYYY-MM-DD"
        ) from error


def symbol(row: Mapping[str, object]) -> str:
    value = row.get("stock_id")
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(
            "FINMIND_HISTORICAL_SYMBOL_INVALID", "historical row requires stock_id"
        )
    return value.strip()


def _number(row: Mapping[str, object], field: str) -> Decimal | None:
    raw = row.get(field)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool):
        raise IngestionError(
            "FINMIND_HISTORICAL_NUMBER_INVALID", f"{field} must be numeric"
        )
    try:
        value = Decimal(str(raw).replace(",", ""))
    except InvalidOperation as error:
        raise IngestionError(
            "FINMIND_HISTORICAL_NUMBER_INVALID", f"{field} must be numeric"
        ) from error
    if not value.is_finite() or value < 0:
        raise IngestionError(
            "FINMIND_HISTORICAL_NUMBER_INVALID", f"{field} must be non-negative"
        )
    return value


def _decimal_text(value: Decimal | None, *, scale: int) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(1).scaleb(-scale)).normalize(), "f")


def _price_ratio(
    row: Mapping[str, object], before_field: str, after_field: str
) -> str | None:
    before = _number(row, before_field)
    after = _number(row, after_field)
    if before is None or after is None or before == 0 or after == 0:
        return None
    return _decimal_text(before / after, scale=10)


def _row_hash(dataset: str, row: Mapping[str, object]) -> str:
    encoded = json.dumps(
        {"dataset": dataset, "source_row": dict(row)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def identity_index(
    identities: Sequence[HistoricalEvidenceIdentity],
) -> Mapping[str, tuple[HistoricalEvidenceIdentity, ...]]:
    grouped: defaultdict[str, list[HistoricalEvidenceIdentity]] = defaultdict(list)
    for identity in identities:
        grouped[identity.source_symbol].append(identity)
    return {symbol: tuple(rows) for symbol, rows in grouped.items()}


def resolve_identity(
    index: Mapping[str, tuple[HistoricalEvidenceIdentity, ...]],
    *,
    source_symbol: str,
    on_date: date,
    observed_at: datetime,
) -> tuple[dict[str, object], tuple[str, ...]]:
    matches = [
        item
        for item in index.get(source_symbol, ())
        if item.covers(on_date, observed_at)
    ]
    if len(matches) == 1:
        item = matches[0]
        return (
            {
                "listing_evidence_id": item.listing_evidence_id,
                "listing_period_id": item.listing_period_id,
                "security_id": item.security_id,
                "identity_resolution_status": "VERIFIED",
            },
            (),
        )
    status = "CONFLICT" if len(matches) > 1 else "UNRESOLVED"
    reason = (
        "HISTORICAL_IDENTITY_CONFLICT"
        if status == "CONFLICT"
        else "HISTORICAL_IDENTITY_UNRESOLVED"
    )
    return (
        {
            "listing_evidence_id": None,
            "listing_period_id": None,
            "security_id": None,
            "identity_resolution_status": status,
        },
        (reason,),
    )


def lineage(
    payload: ProviderPayload, row: Mapping[str, object], *, source_id: int
) -> dict[str, object]:
    observed = payload.retrieved_at.astimezone(timezone.utc).isoformat()
    return {
        "source_id": source_id,
        "source_dataset": payload.dataset,
        "source_version": revision_version(payload),
        "source_revision_hash": _row_hash(payload.dataset, row),
        "source_payload_hash": payload.payload_sha256,
        "source_url": payload.source_url,
        "source_row": dict(row),
        "first_observed_at": observed,
        "available_at": observed,
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
    }


def action_terms(
    dataset: str, row: Mapping[str, object]
) -> tuple[str, dict[str, object], tuple[str, ...]]:
    terms: dict[str, object] = {
        "cash_amount_per_share": None,
        "share_ratio": None,
        "share_multiplier": None,
        "subscription_price_per_share": None,
        "reference_price_adjustment": None,
    }
    if dataset == "dividend_results":
        label = str(row.get("stock_or_cache_dividend") or "").strip()
        action_type = (
            "CASH_DIVIDEND"
            if "息" in label and "權" not in label
            else "STOCK_DIVIDEND"
            if "權" in label and "息" not in label
            else "OTHER"
        )
        terms["reference_price_adjustment"] = _decimal_text(
            _number(row, "stock_and_cache_dividend"), scale=8
        )
        reason = (
            "COMBINED_OR_UNKNOWN_DIVIDEND_RESULT_NOT_DECOMPOSED"
            if action_type == "OTHER"
            else "DIVIDEND_RESULT_TERMS_INCOMPLETE"
        )
        return action_type, terms, (reason,)
    if dataset == "stock_splits":
        kind = str(row.get("type") or "").strip()
        terms["share_multiplier"] = _price_ratio(row, "before_price", "after_price")
        reason = (
            "SPLIT_MULTIPLIER_DERIVED_FROM_REFERENCE_PRICE"
            if terms["share_multiplier"] is not None
            else "SPLIT_MULTIPLIER_UNAVAILABLE"
        )
        return (
            "SPLIT" if kind in {"分割", "反分割"} else "OTHER",
            terms,
            (reason,),
        )
    terms["share_multiplier"] = _price_ratio(row, "before_close", "after_ref_close")
    reason = (
        "PAR_VALUE_MULTIPLIER_DERIVED_FROM_REFERENCE_PRICE"
        if terms["share_multiplier"] is not None
        else "PAR_VALUE_MULTIPLIER_UNAVAILABLE"
    )
    return "SPLIT", terms, (reason,)


def state_timestamp(raw_date: object, raw_time: object) -> str | None:
    if not isinstance(raw_date, str) or not isinstance(raw_time, str):
        return None
    if not raw_date.strip() or not raw_time.strip():
        return None
    try:
        local = datetime.combine(
            date.fromisoformat(raw_date.strip()),
            time.fromisoformat(raw_time.strip()),
            tzinfo=TAIPEI,
        )
    except ValueError:
        return None
    return local.astimezone(timezone.utc).isoformat()
