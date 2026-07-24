"""Export point-in-time Decision Policy evidence from Production facts."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
import re
from typing import Protocol, cast

from src.pipeline.research_decision_policy_evidence import (
    DecisionPolicyEvidenceSnapshot,
    RequiredEvidenceCategory,
    RequiredPolicyEvidence,
)


_SYMBOL = re.compile(r"[0-9A-Z]{2,12}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TRADABILITY_FIELDS = (
    "trading_status",
    "attention_flag",
    "disposal_flag",
    "altered_trading_method_flag",
    "full_cash_delivery_flag",
    "periodic_auction_flag",
    "suspended_flag",
)


class DecisionPolicyEvidenceReader(Protocol):
    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        page_size: int = 1_000,
        max_rows: int = 10_000,
    ) -> list[dict[str, object]]: ...


def _aware(value: object, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _date(value: object, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO date") from error
    if parsed.isoformat() != str(value):
        raise ValueError(f"{field_name} must be an ISO date")
    return parsed


def _positive_id(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        parsed = int(cast(int | str, value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _tradability_details(row: Mapping[str, object]) -> dict[str, object]:
    return {name: row.get(name) for name in _TRADABILITY_FIELDS}


def _source_metadata(
    row: Mapping[str, object],
    sources: Mapping[int, Mapping[str, object]],
    *,
    expected_source: str,
) -> tuple[str | None, str | None]:
    source_id = _positive_id(row.get("source_id"), "security history source_id")
    source = sources.get(source_id)
    if (
        source is None
        or source.get("is_active") is not True
        or source.get("source_code") != expected_source
    ):
        return None, None
    revision = row.get("source_revision_hash")
    if not isinstance(revision, str) or _SHA256.fullmatch(revision) is None:
        return str(source["source_code"]), None
    return str(source["source_code"]), revision


def _missing_tradability(
    *,
    market: str,
    symbol: str,
    reason_code: str,
    row: Mapping[str, object] | None = None,
    sources: Mapping[int, Mapping[str, object]] | None = None,
) -> RequiredPolicyEvidence:
    source: str | None = None
    publication_id: str | None = None
    effective_date: date | None = None
    available_at: datetime | None = None
    details: Mapping[str, object] = {}
    if row is not None:
        source, publication_id = _source_metadata(
            row,
            sources or {},
            expected_source=f"{market}_MOPS_SNAPSHOT",
        )
        effective_date = _date(row.get("effective_from"), "security effective_from")
        available_at = _aware(row.get("available_at"), "security available_at")
        details = _tradability_details(row)
    return RequiredPolicyEvidence.missing(
        category=RequiredEvidenceCategory.TRADABILITY,
        market=market,
        symbol=symbol,
        reason_code=reason_code,
        source=source,
        effective_date=effective_date,
        available_at=available_at,
        publication_id=publication_id,
        details=details,
    )


def _tradability_evidence(
    *,
    market: str,
    as_of_date: date,
    decision_at: datetime,
    securities: Mapping[str, int],
    history: Sequence[Mapping[str, object]],
    sources: Mapping[int, Mapping[str, object]],
) -> tuple[RequiredPolicyEvidence, ...]:
    by_security: dict[int, list[Mapping[str, object]]] = {}
    allowed_ids = set(securities.values())
    for row in history:
        security_id = _positive_id(row.get("security_id"), "security_history security_id")
        if (
            security_id not in allowed_ids
            or row.get("record_kind") != "CURRENT_DAILY_SNAPSHOT"
            or row.get("snapshot_date") != as_of_date.isoformat()
            or row.get("effective_from") != as_of_date.isoformat()
            or row.get("effective_to") != (as_of_date + timedelta(days=1)).isoformat()
        ):
            continue
        by_security.setdefault(security_id, []).append(row)

    evidence: list[RequiredPolicyEvidence] = []
    for symbol, security_id in sorted(securities.items()):
        rows = by_security.get(security_id, [])
        if not rows:
            evidence.append(
                _missing_tradability(
                    market=market,
                    symbol=symbol,
                    reason_code="TRADABILITY_EVIDENCE_NOT_OBSERVED",
                )
            )
            continue
        ordered = sorted(
            rows,
            key=lambda row: _aware(row.get("available_at"), "security available_at"),
            reverse=True,
        )
        safe = [
            row
            for row in ordered
            if _aware(row.get("available_at"), "security available_at") <= decision_at
        ]
        if not safe:
            evidence.append(
                _missing_tradability(
                    market=market,
                    symbol=symbol,
                    reason_code="TRADABILITY_EVIDENCE_AVAILABLE_AFTER_DECISION",
                    row=ordered[-1],
                    sources=sources,
                )
            )
            continue
        selected = safe[0]
        selected_at = _aware(selected.get("available_at"), "security available_at")
        peers = [
            row
            for row in safe
            if _aware(row.get("available_at"), "security available_at") == selected_at
        ]
        peer_states = {
            (
                row.get("source_id"),
                row.get("source_version"),
                row.get("source_revision_hash"),
                *(row.get(name) for name in _TRADABILITY_FIELDS),
            )
            for row in peers
        }
        if len(peer_states) != 1:
            raise ValueError("conflicting tradability evidence has the same availability time")
        source, revision = _source_metadata(
            selected,
            sources,
            expected_source=f"{market}_MOPS_SNAPSHOT",
        )
        if source is None or revision is None:
            evidence.append(
                _missing_tradability(
                    market=market,
                    symbol=symbol,
                    reason_code="TRADABILITY_EVIDENCE_SOURCE_INVALID",
                    row=selected,
                    sources=sources,
                )
            )
            continue
        details = _tradability_details(selected)
        if (
            details["trading_status"] not in {"ACTIVE", "SUSPENDED", "STOPPED", "DELISTED"}
            or any(
                not isinstance(details[name], bool)
                for name in _TRADABILITY_FIELDS
                if name != "trading_status"
            )
            or not isinstance(selected.get("source_version"), str)
            or not str(selected.get("source_version")).strip()
        ):
            evidence.append(
                _missing_tradability(
                    market=market,
                    symbol=symbol,
                    reason_code="TRADABILITY_EVIDENCE_INCOMPLETE",
                    row=selected,
                    sources=sources,
                )
            )
            continue
        tradable = (
            details["trading_status"] == "ACTIVE"
            and details["disposal_flag"] is False
            and details["altered_trading_method_flag"] is False
            and details["full_cash_delivery_flag"] is False
            and details["periodic_auction_flag"] is False
            and details["suspended_flag"] is False
        )
        evidence.append(
            RequiredPolicyEvidence.available(
                category=RequiredEvidenceCategory.TRADABILITY,
                value=tradable,
                source=source,
                market=market,
                symbol=symbol,
                effective_date=as_of_date,
                available_at=selected_at,
                publication_id=revision,
                details=details,
            )
        )
    return tuple(evidence)


def _market_evidence(
    *,
    market: str,
    as_of_date: date,
    decision_at: datetime,
    runs: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
) -> RequiredPolicyEvidence:
    candidates: list[Mapping[str, object]] = []
    for row in runs:
        if (
            row.get("as_of_date") != as_of_date.isoformat()
            or row.get("market_scope") != market
            or int(cast(int | str, row.get("horizon"))) != 5
        ):
            continue
        if _aware(row.get("decision_at"), "market run decision_at") <= decision_at:
            candidates.append(row)
    if not candidates:
        return RequiredPolicyEvidence.missing(
            category=RequiredEvidenceCategory.MARKET_EXPOSURE,
            market=market,
            symbol=None,
            reason_code="MARKET_EXPOSURE_PRODUCER_UNAVAILABLE",
        )
    scoped = [
        row
        for row in candidates
        if max(
            _aware(
                row.get("latest_available_at"),
                "market run latest_available_at",
            ),
            _aware(row.get("created_at"), "market run created_at"),
        )
        <= decision_at
    ]
    selectable = scoped or candidates
    selected_run = max(
        selectable,
        key=lambda row: (
            _aware(row.get("decision_at"), "market run decision_at"),
            _positive_id(row.get("prediction_run_id"), "prediction_run_id"),
        ),
    )
    run_id = _positive_id(selected_run.get("prediction_run_id"), "prediction_run_id")
    rows = [
        row
        for row in predictions
        if _positive_id(row.get("prediction_run_id"), "market prediction run_id") == run_id
        and row.get("market") == market
    ]
    if len(rows) > 1:
        raise ValueError("market exposure publication is not unique")
    available_at = max(
        _aware(
            selected_run.get("latest_available_at"),
            "market run latest_available_at",
        ),
        _aware(selected_run.get("created_at"), "market run created_at"),
    )
    if not rows:
        return RequiredPolicyEvidence.missing(
            category=RequiredEvidenceCategory.MARKET_EXPOSURE,
            market=market,
            symbol=None,
            reason_code="MARKET_EXPOSURE_PRODUCER_UNAVAILABLE",
            available_at=available_at,
            publication_id=f"prediction_run:{run_id}",
        )
    row = rows[0]
    model_version = _text(row.get("model_version"), "market model_version")
    available_at = max(
        available_at,
        _aware(row.get("created_at"), "market prediction created_at"),
    )
    if not scoped or available_at > decision_at:
        return RequiredPolicyEvidence.missing(
            category=RequiredEvidenceCategory.MARKET_EXPOSURE,
            market=market,
            symbol=None,
            reason_code="MARKET_EXPOSURE_AVAILABLE_AFTER_DECISION",
            source=f"MARKET_PREDICTION:{model_version}",
            effective_date=as_of_date,
            available_at=available_at,
            publication_id=f"prediction_run:{run_id}",
            details=dict(row),
        )
    if selected_run.get("system_validation_status") != "PASS":
        return RequiredPolicyEvidence.missing(
            category=RequiredEvidenceCategory.MARKET_EXPOSURE,
            market=market,
            symbol=None,
            reason_code="MARKET_EXPOSURE_NOT_FORMALLY_VALIDATED",
            source=f"MARKET_PREDICTION:{model_version}",
            effective_date=as_of_date,
            available_at=available_at,
            publication_id=f"prediction_run:{run_id}",
            details=dict(row),
        )
    details = {
        "calibrated_p_up": float(cast(float | int | str, row.get("calibrated_p_up"))),
        "calibrated_p_neutral": float(cast(float | int | str, row.get("calibrated_p_neutral"))),
        "calibrated_p_down": float(cast(float | int | str, row.get("calibrated_p_down"))),
        "market_regime": _text(row.get("market_regime"), "market_regime"),
        "forecast_market_volatility": float(
            cast(float | int | str, row.get("forecast_market_volatility"))
        ),
        "model_version": model_version,
        "training_end_date": _date(
            row.get("training_end_date"),
            "market training_end_date",
        ).isoformat(),
    }
    return RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.MARKET_EXPOSURE,
        value=float(cast(float | int | str, row.get("market_exposure_cap"))),
        source=f"MARKET_PREDICTION:{model_version}",
        market=market,
        symbol=None,
        effective_date=as_of_date,
        available_at=available_at,
        publication_id=f"prediction_run:{run_id}",
        details=details,
    )


def export_decision_policy_evidence(
    writer: DecisionPolicyEvidenceReader,
    *,
    market: str,
    as_of_date: date,
    decision_at: datetime,
    securities: Mapping[str, int],
    publication_id: str,
) -> DecisionPolicyEvidenceSnapshot:
    """Export only exact-date, pre-decision evidence for the supplied universe."""

    normalized_market = market.strip().upper()
    if normalized_market not in {"TWSE", "TPEX"}:
        raise ValueError("Decision Policy evidence market is unsupported")
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("Decision Policy evidence decision_at must be timezone-aware")
    if decision_at.date() != as_of_date:
        raise ValueError("Decision Policy evidence date does not match decision_at")
    if not securities:
        raise ValueError("Decision Policy evidence universe cannot be empty")
    normalized_securities: dict[str, int] = {}
    seen_ids: set[int] = set()
    for symbol, raw_security_id in securities.items():
        if _SYMBOL.fullmatch(symbol) is None:
            raise ValueError("Decision Policy evidence contains an unsafe symbol")
        security_id = _positive_id(raw_security_id, "security_id")
        if security_id in seen_ids:
            raise ValueError("Decision Policy evidence security IDs must be unique")
        seen_ids.add(security_id)
        normalized_securities[symbol] = security_id

    history = writer.select_all_rows(
        "security_history",
        select=(
            "security_id,record_kind,snapshot_date,effective_from,effective_to,"
            "trading_status,attention_flag,disposal_flag,"
            "altered_trading_method_flag,full_cash_delivery_flag,"
            "periodic_auction_flag,suspended_flag,source_id,source_version,"
            "source_revision_hash,available_at"
        ),
        filters={
            "record_kind": "eq.CURRENT_DAILY_SNAPSHOT",
            "snapshot_date": f"eq.{as_of_date.isoformat()}",
            "order": "security_id.asc,available_at.desc",
        },
        page_size=1_000,
        max_rows=5_000,
    )
    source_rows = writer.select_all_rows(
        "data_sources",
        select="source_id,source_code,is_active",
        filters={"order": "source_id.asc"},
        page_size=100,
        max_rows=1_000,
    )
    sources = {_positive_id(row.get("source_id"), "data source_id"): row for row in source_rows}
    runs = writer.select_all_rows(
        "prediction_runs",
        select=(
            "prediction_run_id,as_of_date,decision_at,horizon,market_scope,"
            "system_validation_status,latest_available_at,created_at"
        ),
        filters={
            "as_of_date": f"eq.{as_of_date.isoformat()}",
            "horizon": "eq.5",
            "market_scope": f"eq.{normalized_market}",
            "order": "decision_at.desc,prediction_run_id.desc",
        },
        page_size=100,
        max_rows=1_000,
    )
    run_ids = {_positive_id(row.get("prediction_run_id"), "prediction_run_id") for row in runs}
    market_rows = (
        []
        if not run_ids
        else writer.select_all_rows(
            "market_predictions",
            select=(
                "prediction_run_id,market,calibrated_p_up,"
                "calibrated_p_neutral,calibrated_p_down,market_regime,"
                "forecast_market_volatility,market_exposure_cap,"
                "model_version,training_end_date,created_at"
            ),
            filters={
                "prediction_run_id": (f"in.({','.join(str(value) for value in sorted(run_ids))})"),
                "market": f"eq.{normalized_market}",
                "order": "prediction_run_id.desc",
            },
            page_size=100,
            max_rows=1_000,
        )
    )

    tradability = _tradability_evidence(
        market=normalized_market,
        as_of_date=as_of_date,
        decision_at=decision_at,
        securities=normalized_securities,
        history=history,
        sources=sources,
    )
    market_evidence = _market_evidence(
        market=normalized_market,
        as_of_date=as_of_date,
        decision_at=decision_at,
        runs=runs,
        predictions=market_rows,
    )
    position = tuple(
        RequiredPolicyEvidence.missing(
            category=RequiredEvidenceCategory.POSITION_LIMITS,
            market=normalized_market,
            symbol=symbol,
            reason_code="POSITION_LIMIT_PRODUCER_UNAVAILABLE",
        )
        for symbol in sorted(normalized_securities)
    )
    return DecisionPolicyEvidenceSnapshot(
        market=normalized_market,
        as_of_date=as_of_date,
        decision_at=decision_at,
        evidence=(*tradability, market_evidence, *position),
        publication_id=publication_id,
    )


__all__ = [
    "DecisionPolicyEvidenceReader",
    "export_decision_policy_evidence",
]
