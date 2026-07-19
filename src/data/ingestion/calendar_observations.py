"""Build append-only research evidence from date-only FinMind sessions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timezone
from hashlib import sha256
import json
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .normalizers import revision_version


DATE_ONLY_REASON_CODES = (
    "FINMIND_HISTORICAL_VINTAGE_UNAVAILABLE",
    "OFFICIAL_SESSION_TIMES_UNAVAILABLE",
    "DECISION_DATA_CUTOFF_UNAVAILABLE",
    "OFFICIAL_PUBLICATION_TIME_UNAVAILABLE",
    "FIRST_OBSERVED_AT_RETRIEVAL",
)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _source_rows_by_date(payload: ProviderPayload) -> dict[str, Mapping[str, object]]:
    body = cast(object, payload.payload)
    if not isinstance(body, Mapping):
        raise IngestionError(
            "TRADING_CALENDAR_PAYLOAD_INVALID",
            "FinMind trading-calendar payload must be an object",
        )
    raw_rows = cast(Mapping[str, object], body).get("data")
    if not isinstance(raw_rows, list):
        raise IngestionError(
            "TRADING_CALENDAR_PAYLOAD_INVALID",
            "FinMind trading-calendar payload must contain a data array",
        )
    rows = cast(list[object], raw_rows)
    if not all(isinstance(row, Mapping) for row in rows):
        raise IngestionError(
            "TRADING_CALENDAR_PAYLOAD_INVALID",
            "FinMind trading-calendar payload must contain object rows",
        )

    indexed: dict[str, Mapping[str, object]] = {}
    for raw in rows:
        row = cast(Mapping[str, object], raw)
        source_date = str(row.get("date") or "").strip()
        if not source_date or source_date in indexed:
            raise IngestionError(
                "TRADING_CALENDAR_OBSERVATION_LINEAGE_INVALID",
                "Every normalized session requires one unique source row",
            )
        indexed[source_date] = row
    return indexed


def normalize_finmind_calendar_observations(
    payload: ProviderPayload,
    sessions: Sequence[Mapping[str, object]],
    *,
    source_id: int,
) -> list[dict[str, object]]:
    """Map date hints to auditable rows without claiming verified session times."""

    if source_id <= 0:
        raise ValueError("source_id must be positive")
    if payload.provider != "FINMIND" or payload.dataset != "trading_calendar":
        raise IngestionError(
            "TRADING_CALENDAR_SOURCE_INVALID",
            "Calendar observations require the configured FinMind dataset",
        )
    source_rows = _source_rows_by_date(payload)
    observed_at = payload.retrieved_at.astimezone(timezone.utc).isoformat()
    source_version = revision_version(payload)
    observations: list[dict[str, object]] = []

    for session in sessions:
        market = str(session.get("market") or "").strip().upper()
        trading_date = str(session.get("trading_date") or "").strip()
        source_row = source_rows.get(trading_date)
        if market != "TWSE" or source_row is None:
            raise IngestionError(
                "TRADING_CALENDAR_OBSERVATION_LINEAGE_INVALID",
                "A TWSE session could not be bound to its exact FinMind source row",
            )
        row_identity = {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "source_version": payload.source_version,
            "market": market,
            "trading_date": trading_date,
            "source_row": dict(source_row),
        }
        observations.append(
            {
                "market": market,
                "trading_date": trading_date,
                "is_trading_day": True,
                "opens_at": None,
                "closes_at": None,
                "decision_data_cutoff_at": None,
                "market_basis": "SCHEDULING_HINT",
                "calendar_verification_status": "UNRESOLVED",
                "source_id": source_id,
                "source_dataset": "TaiwanStockTradingDate",
                "source_event_id": f"FINMIND:{market}:{trading_date}",
                "source_version": source_version,
                "source_revision_hash": _canonical_hash(row_identity),
                "source_payload_hash": payload.payload_sha256,
                "source_url": payload.source_url,
                "source_row": dict(source_row),
                "first_observed_at": observed_at,
                "available_at": observed_at,
                "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
                "usage_scope": "CALENDAR_RESEARCH_ONLY",
                "system_status": "RESEARCH_ONLY",
                "reason_codes": list(DATE_ONLY_REASON_CODES),
            }
        )
    return observations
