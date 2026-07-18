"""Normalize current TWSE and TPEx ex-rights announcement snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .corporate_action_contracts import NormalizedCorporateActions
from .normalizers import revision_version
from .roc_date import parse_exchange_date


ZERO = Decimal("0")
MISSING_NUMERIC = {"", "-", "--", "---", "n/a", "null", "none", "尚未公告"}
EXPECTED_CONTRACTS = {
    "TWSE": ("TWSE", "ex_rights"),
    "TPEX": ("TPEX", "ex_rights_forecast"),
}


def _records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, list):
        raise IngestionError(
            "CORPORATE_ACTION_PAYLOAD_INVALID",
            "Corporate-action sources must return arrays of objects",
        )
    items = cast(list[object], raw)
    if not all(isinstance(row, Mapping) for row in items):
        raise IngestionError(
            "CORPORATE_ACTION_PAYLOAD_INVALID",
            "Corporate-action sources must return arrays of objects",
        )
    return [cast(Mapping[str, object], row) for row in items]


def _optional_non_negative_decimal(
    value: object,
    *,
    field: str,
) -> Decimal | None:
    text = "" if value is None else str(value).strip().replace(",", "")
    if text.casefold() in MISSING_NUMERIC:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise IngestionError(
            "CORPORATE_ACTION_VALUE_INVALID",
            f"{field} must be a non-negative number",
        ) from error
    if not parsed.is_finite() or parsed < ZERO:
        raise IngestionError(
            "CORPORATE_ACTION_VALUE_INVALID",
            f"{field} must be a non-negative number",
        )
    return parsed


def _action_row(
    *,
    security_id: int,
    symbol: str,
    action_type: str,
    ex_date: date,
    amount: Decimal,
    amount_field: str,
    source_id: int,
    source_dataset: str,
    source_action_label: str,
    source_version: str,
    source_revision_hash: str,
    source_payload_hash: str,
    first_observed_at: str,
) -> dict[str, object]:
    row: dict[str, object] = {
        "security_id": security_id,
        "action_type": action_type,
        "action_status": "ANNOUNCED",
        "ex_date": ex_date.isoformat(),
        "payable_date": None,
        "cash_amount_per_share": None,
        "share_ratio": None,
        "share_multiplier": None,
        "reference_price_adjustment": None,
        "announced_at": None,
        "first_observed_at": first_observed_at,
        "available_at": first_observed_at,
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        # Forecast endpoints do not expose actual announcement time, payable
        # date, delivery date, or a complete corporate-action lifecycle.
        "source_row_complete": False,
        "source_dataset": source_dataset,
        "source_action_label": source_action_label or None,
        "source_id": source_id,
        "source_event_id": (
            f"{source_dataset}:{symbol}:{action_type}:{ex_date.isoformat()}"
        ),
        "source_version": source_version,
        "source_revision_hash": source_revision_hash,
        "source_payload_hash": source_payload_hash,
        "reason_codes": [
            "CURRENT_EX_RIGHTS_FORECAST_ONLY",
            "CORPORATE_ACTION_ANNOUNCEMENT_TIME_UNKNOWN",
            "CORPORATE_ACTION_PAYABLE_DATE_UNKNOWN",
        ],
    }
    row[amount_field] = str(amount)
    if action_type == "STOCK_DIVIDEND":
        row["share_multiplier"] = str(Decimal("1") + amount)
    return row


def _source_row_hash(
    payload: ProviderPayload,
    raw: Mapping[str, object],
) -> str:
    canonical = json.dumps(
        {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "row": dict(raw),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _market_fields(market: str) -> tuple[str, str, str, str, str]:
    if market == "TWSE":
        return (
            "Code",
            "Date",
            "CashDividend",
            "StockDividendRatio",
            "SubscriptionRatio",
        )
    if market == "TPEX":
        return (
            "SecuritiesCompanyCode",
            "ExRrightsExDividendDate",
            "CashDividend",
            "StockDividendRatio",
            "SubscriptionRatioToNewSharesIssued",
        )
    raise ValueError("market must be TWSE or TPEX")


def normalize_announced_corporate_actions(
    payload: ProviderPayload,
    *,
    market: str,
    source_id: int,
    security_ids: Mapping[tuple[str, str], int],
) -> NormalizedCorporateActions:
    """Map only cash and stock dividends; unsupported components stay explicit."""

    if source_id <= 0:
        raise ValueError("source_id must be positive")
    if (payload.provider, payload.dataset) != EXPECTED_CONTRACTS.get(market):
        raise IngestionError(
            "CORPORATE_ACTION_SOURCE_INVALID",
            "Corporate-action provider or dataset does not match the market",
        )
    symbol_key, date_key, cash_key, stock_key, rights_key = _market_fields(market)
    version = revision_version(payload)
    observed_at = payload.retrieved_at.isoformat()
    normalized: dict[tuple[int, str, str], dict[str, object]] = {}
    excluded_unknown = 0
    excluded_no_supported = 0
    omitted_rights = 0
    unresolved_components = 0
    coverage_dates: set[date] = set()

    for raw in _records(payload):
        symbol = str(raw.get(symbol_key) or "").strip()
        security_id = security_ids.get((market, symbol))
        if security_id is None:
            excluded_unknown += 1
            continue
        ex_date = parse_exchange_date(raw.get(date_key))
        action_label_key = "Exdividend" if market == "TWSE" else "ExRrightsExDividend"
        action_label = str(raw.get(action_label_key) or "").strip()
        cash = _optional_non_negative_decimal(
            raw.get(cash_key), field="cash dividend"
        )
        stock = _optional_non_negative_decimal(
            raw.get(stock_key), field="stock dividend ratio"
        )
        rights = _optional_non_negative_decimal(
            raw.get(rights_key), field="rights ratio"
        )
        if rights is not None and rights > ZERO:
            omitted_rights += 1
        if "息" in action_label and cash is None:
            unresolved_components += 1
        if (
            ("權" in action_label or "权" in action_label)
            and stock is None
            and (rights is None or rights == ZERO)
        ):
            unresolved_components += 1

        rows_for_source: list[dict[str, object]] = []
        row_revision_hash = _source_row_hash(payload, raw)
        if cash is not None and cash > ZERO:
            rows_for_source.append(
                _action_row(
                    security_id=security_id,
                    symbol=symbol,
                    action_type="CASH_DIVIDEND",
                    ex_date=ex_date,
                    amount=cash,
                    amount_field="cash_amount_per_share",
                    source_id=source_id,
                    source_dataset=payload.dataset,
                    source_action_label=action_label,
                    source_version=version,
                    source_revision_hash=row_revision_hash,
                    source_payload_hash=payload.payload_sha256,
                    first_observed_at=observed_at,
                )
            )
        if stock is not None and stock > ZERO:
            rows_for_source.append(
                _action_row(
                    security_id=security_id,
                    symbol=symbol,
                    action_type="STOCK_DIVIDEND",
                    ex_date=ex_date,
                    amount=stock,
                    amount_field="share_ratio",
                    source_id=source_id,
                    source_dataset=payload.dataset,
                    source_action_label=action_label,
                    source_version=version,
                    source_revision_hash=row_revision_hash,
                    source_payload_hash=payload.payload_sha256,
                    first_observed_at=observed_at,
                )
            )
        if not rows_for_source:
            excluded_no_supported += 1
            continue
        coverage_dates.add(ex_date)
        for row in rows_for_source:
            action_type = str(row["action_type"])
            key = (security_id, action_type, ex_date.isoformat())
            previous = normalized.get(key)
            if previous is not None and previous != row:
                raise IngestionError(
                    "CORPORATE_ACTION_DUPLICATE_CONFLICT",
                    "One source snapshot contains conflicting action components",
                )
            normalized[key] = row

    ordered = tuple(
        normalized[key]
        for key in sorted(normalized, key=lambda item: (item[2], item[0], item[1]))
    )
    return NormalizedCorporateActions(
        rows=ordered,
        excluded_unknown_securities=excluded_unknown,
        excluded_no_supported_component_rows=excluded_no_supported,
        omitted_rights_components=omitted_rights,
        unresolved_announced_components=unresolved_components,
        observed_ex_date_min=min(coverage_dates, default=None),
        observed_ex_date_max=max(coverage_dates, default=None),
    )
