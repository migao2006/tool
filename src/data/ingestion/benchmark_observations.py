"""Normalize official current-month total-return index closes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import cast
from zoneinfo import ZoneInfo

from src.data.providers.contracts import ProviderPayload

from .benchmark_contracts import BENCHMARK_REASON_CODES, BENCHMARK_SPECS
from .contracts import IngestionError
from .roc_date import parse_exchange_date


TAIPEI = ZoneInfo("Asia/Taipei")


def _records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, list):
        raise IngestionError(
            "BENCHMARK_PAYLOAD_INVALID",
            "Benchmark sources must return arrays of objects",
        )
    items = cast(list[object], raw)
    if not all(isinstance(row, Mapping) for row in items):
        raise IngestionError(
            "BENCHMARK_PAYLOAD_INVALID",
            "Benchmark source rows must be objects",
        )
    return [cast(Mapping[str, object], row) for row in items]


def _positive_decimal(value: object) -> Decimal:
    text = "" if value is None else str(value).strip().replace(",", "")
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise IngestionError(
            "BENCHMARK_OBSERVATION_INVALID",
            "Total-return index level must be a positive finite number",
        ) from error
    if not parsed.is_finite() or parsed <= 0:
        raise IngestionError(
            "BENCHMARK_OBSERVATION_INVALID",
            "Total-return index level must be a positive finite number",
        )
    return parsed


def _row_hash(*, series_code: str, session_date: str, value: str) -> str:
    canonical = json.dumps(
        {
            "series_code": series_code,
            "session_date": session_date,
            "value": value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def normalize_total_return_index(
    payload: ProviderPayload,
    *,
    market: str,
    source_id: int,
) -> list[dict[str, object]]:
    """Return one point-in-time row per official daily close."""

    if source_id <= 0:
        raise ValueError("source_id must be positive")
    spec = BENCHMARK_SPECS.get(market)
    if spec is None:
        raise ValueError("market must be TWSE or TPEX")
    if (payload.provider, payload.dataset) != (spec.provider, spec.dataset):
        raise IngestionError(
            "BENCHMARK_SOURCE_INVALID",
            "Benchmark provider or dataset does not match the market",
        )
    observed_at = payload.retrieved_at.isoformat()
    normalized: dict[str, dict[str, object]] = {}
    for raw in _records(payload):
        try:
            session_date = parse_exchange_date(raw.get("Date"))
            value = _positive_decimal(raw.get(spec.remote_field))
        except IngestionError as error:
            raise IngestionError(
                "BENCHMARK_OBSERVATION_INVALID",
                "Benchmark row has an invalid date or index level",
            ) from error
        value_text = str(value)
        session_text = session_date.isoformat()
        revision_hash = _row_hash(
            series_code=spec.series_code,
            session_date=session_text,
            value=value_text,
        )
        row: dict[str, object] = {
            "series_code": spec.series_code,
            "observation_at": datetime.combine(
                session_date, time(13, 30), tzinfo=TAIPEI
            ).isoformat(),
            "numeric_value": value_text,
            "text_value": None,
            "source_id": source_id,
            "source_version": (
                f"{payload.source_version}+row-sha256:{revision_hash[:16]}"
            ),
            "available_at": observed_at,
            "benchmark_id": None,
            "source_dataset": payload.dataset,
            "observation_kind": "TOTAL_RETURN_INDEX_LEVEL",
            "first_observed_at": observed_at,
            "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
            "usage_scope": "LABEL_TARGET_ONLY",
            "alignment_status": "RESEARCH_ONLY",
            "reason_codes": list(BENCHMARK_REASON_CODES),
            "source_revision_hash": revision_hash,
            "source_payload_hash": payload.payload_sha256,
        }
        previous = normalized.get(session_text)
        if previous is not None and previous != row:
            raise IngestionError(
                "BENCHMARK_DUPLICATE_CONFLICT",
                "One benchmark snapshot contains conflicting closes for one date",
            )
        normalized[session_text] = row
    return [normalized[key] for key in sorted(normalized)]
