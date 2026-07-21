"""Normalize FinMind action and suspension history as research-only evidence."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .finmind_historical_evidence_contracts import (
    HistoricalEvidenceIdentity,
    NormalizedFinMindHistoricalEvidence,
)
from .finmind_historical_evidence_rows import (
    BASE_ACTION_REASONS,
    BASE_STATE_REASONS,
    SUPPORTED_DATASETS,
    TAIPEI,
    action_terms,
    event_date,
    identity_index,
    lineage,
    records,
    resolve_identity,
    state_timestamp,
    symbol,
    validate_twse_common_symbols,
)


def normalize_finmind_historical_evidence(
    payloads: Sequence[ProviderPayload],
    *,
    source_id: int,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    identities: Sequence[HistoricalEvidenceIdentity] = (),
    expected_datasets: Collection[str] | None = None,
) -> NormalizedFinMindHistoricalEvidence:
    """Build append-only action rows and canonical partial state-event rows."""

    if isinstance(source_id, bool) or source_id <= 0:
        raise ValueError("source_id must be a positive integer")
    if end_date < start_date:
        raise IngestionError(
            "FINMIND_HISTORICAL_DATE_RANGE_INVALID",
            "start_date must not be after end_date",
        )
    allowed = set(validate_twse_common_symbols(symbols))
    required_datasets = (
        SUPPORTED_DATASETS
        if expected_datasets is None
        else frozenset(expected_datasets)
    )
    if not required_datasets or not required_datasets <= SUPPORTED_DATASETS:
        raise IngestionError(
            "FINMIND_HISTORICAL_DATASETS_UNSUPPORTED",
            "expected datasets must be a non-empty supported subset",
        )
    if frozenset(payload.dataset for payload in payloads) != required_datasets:
        raise IngestionError(
            "FINMIND_HISTORICAL_DATASETS_INCOMPLETE",
            "the requested FinMind historical evidence datasets are incomplete",
        )
    identities_by_symbol = identity_index(identities)
    actions: list[dict[str, object]] = []
    states: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    input_rows = outside_request = outside_range = duplicates = 0

    for payload in payloads:
        for source_row in records(payload):
            input_rows += 1
            source_symbol = symbol(source_row)
            if source_symbol not in allowed:
                outside_request += 1
                continue
            on_date = event_date(source_row)
            if on_date < start_date or on_date > end_date:
                outside_range += 1
                continue
            identity, identity_reasons = resolve_identity(
                identities_by_symbol,
                source_symbol=source_symbol,
                on_date=on_date,
                observed_at=payload.retrieved_at,
            )
            event_id = (
                f"FINMIND:{payload.dataset}:{source_symbol}:{on_date.isoformat()}"
            )
            row_lineage = lineage(payload, source_row, source_id=source_id)

            if payload.dataset != "suspended":
                action_type, terms, term_reasons = action_terms(
                    payload.dataset, source_row
                )
                key = (
                    payload.dataset,
                    event_id,
                    action_type,
                    cast(str, row_lineage["source_revision_hash"]),
                )
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                observed_date = payload.retrieved_at.astimezone(TAIPEI).date()
                actions.append(
                    {
                        "action_event_id": f"{event_id}:{action_type}",
                        **identity,
                        "market": "TWSE",
                        "asset_type": "COMMON_STOCK",
                        "source_symbol": source_symbol,
                        "action_type": action_type,
                        "action_status": (
                            "REALIZED" if on_date <= observed_date else "ANNOUNCED"
                        ),
                        "ex_date": on_date.isoformat(),
                        "payable_date": None,
                        "announced_at": None,
                        **terms,
                        "source_row_complete": False,
                        **row_lineage,
                        "source_event_id": event_id,
                        "usage_scope": "ACTION_RESEARCH_ONLY",
                        "system_status": "RESEARCH_ONLY",
                        "reason_codes": list(
                            dict.fromkeys(
                                (*BASE_ACTION_REASONS, *identity_reasons, *term_reasons)
                            )
                        ),
                    }
                )
                continue

            suspension_at = state_timestamp(
                source_row.get("date"), source_row.get("suspension_time")
            )
            resumption_at = state_timestamp(
                source_row.get("resumption_date"),
                source_row.get("resumption_time"),
            )
            key = (
                payload.dataset,
                event_id,
                "TRADING_SUSPENSION_INTERVAL",
                cast(str, row_lineage["source_revision_hash"]),
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            timestamp_reasons = (
                ()
                if suspension_at is not None
                else ("SUSPENSION_TIMESTAMP_UNAVAILABLE",)
            )
            states.append(
                {
                    "state_event_id": event_id,
                    **identity,
                    "market": "TWSE",
                    "asset_type": "COMMON_STOCK",
                    "source_symbol": source_symbol,
                    "event_type": "TRADING_SUSPENSION_INTERVAL",
                    "event_date": on_date.isoformat(),
                    "trading_status": "SUSPENDED",
                    "suspension_at": suspension_at,
                    "resumption_at": resumption_at,
                    "source_row_complete": False,
                    **row_lineage,
                    "source_event_id": event_id,
                    "state_verification_status": "UNRESOLVED",
                    "usage_scope": "SECURITY_STATE_RESEARCH_ONLY",
                    "system_status": "RESEARCH_ONLY",
                    "reason_codes": list(
                        dict.fromkeys(
                            (*BASE_STATE_REASONS, *identity_reasons, *timestamp_reasons)
                        )
                    ),
                }
            )

    return NormalizedFinMindHistoricalEvidence(
        action_rows=tuple(actions),
        state_event_rows=tuple(states),
        input_rows=input_rows,
        excluded_outside_request=outside_request,
        excluded_outside_range=outside_range,
        excluded_duplicates=duplicates,
    )
