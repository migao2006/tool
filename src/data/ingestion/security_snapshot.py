"""Normalize current exchange security state without inventing history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from .contracts import IngestionError
from .security_snapshot_contracts import (
    MarketSnapshotPayloads,
    NormalizedSecuritySnapshot,
)
from .security_snapshot_parsing import (
    active_disposals,
    active_whole_session_suspensions,
    profile_state,
    restriction_state,
    symbols_announced_on,
)


TAIPEI = ZoneInfo("Asia/Taipei")
SNAPSHOT_SOURCE_VERSION = "daily-security-snapshot.v1"
EXPECTED_CONTRACTS = {
    "TWSE": (
        ("MOPS", "listed_company_profile"),
        ("TWSE", "changed_trading"),
        ("TWSE", "suspended"),
        ("TWSE", "attention"),
        ("TWSE", "disposals"),
    ),
    "TPEX": (
        ("MOPS", "otc_company_profile"),
        ("TPEX", "trading_restrictions"),
        ("TPEX", "suspended_history"),
        ("TPEX", "attention"),
        ("TPEX", "disposals"),
    ),
}


def snapshot_revision_hash(payloads: MarketSnapshotPayloads) -> str:
    """Hash the complete source bundle while keeping the parser version stable."""

    evidence = [
        (payload.provider, payload.dataset, payload.source_version, payload.payload_sha256)
        for payload in (
            payloads.profile,
            payloads.restrictions,
            payloads.suspended,
            payloads.attention,
            payloads.disposals,
        )
    ]
    return sha256(
        json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _validate_bundle(
    payloads: MarketSnapshotPayloads,
    *,
    market: str,
    snapshot_date: date,
) -> None:
    if market not in EXPECTED_CONTRACTS:
        raise ValueError("market must be TWSE or TPEX")
    bundle = (
        payloads.profile,
        payloads.restrictions,
        payloads.suspended,
        payloads.attention,
        payloads.disposals,
    )
    actual_contracts = tuple((item.provider, item.dataset) for item in bundle)
    if actual_contracts != EXPECTED_CONTRACTS[market]:
        raise IngestionError(
            "SECURITY_SNAPSHOT_SOURCE_INVALID",
            "Security snapshot provider or dataset contract does not match the market",
        )
    if any(
        payload.retrieved_at.astimezone(TAIPEI).date() != snapshot_date
        for payload in bundle
    ):
        raise IngestionError(
            "SECURITY_SNAPSHOT_DATE_MISMATCH",
            "Current security snapshots cannot be backdated",
        )


def normalize_current_security_snapshot(
    payloads: MarketSnapshotPayloads,
    *,
    market: str,
    snapshot_date: date,
    source_id: int,
    security_ids: Mapping[tuple[str, str], int],
) -> NormalizedSecuritySnapshot:
    """Create one-day current-state rows; this is not historical backfill."""

    if source_id <= 0:
        raise ValueError("source_id must be positive")
    _validate_bundle(payloads, market=market, snapshot_date=snapshot_date)

    industries, profile_date = profile_state(
        payloads.profile,
        market=market,
        snapshot_date=snapshot_date,
    )
    altered, periodic, stopped = restriction_state(
        payloads.restrictions,
        market=market,
        snapshot_date=snapshot_date,
    )
    if market == "TWSE":
        symbol_key, date_key = "Code", "Date"
        suspended, excluded_intraday = active_whole_session_suspensions(
            payloads.suspended,
            symbol_key="Code",
            start_key="TradingHaltDate",
            start_time_key="TradingHaltTime",
            resume_key="TradingResumptionDate",
            snapshot_date=snapshot_date,
        )
    else:
        symbol_key, date_key = "SecuritiesCompanyCode", "Date"
        suspended, excluded_intraday = active_whole_session_suspensions(
            payloads.suspended,
            symbol_key="SecuritiesCompanyCode",
            start_key="DateOfSuspendedTrading",
            start_time_key="TimeOfSuspendedTrading",
            resume_key="DateOfResumedTrading",
            snapshot_date=snapshot_date,
        )

    attention = symbols_announced_on(
        payloads.attention,
        symbol_key=symbol_key,
        date_key=date_key,
        snapshot_date=snapshot_date,
    )
    disposals = active_disposals(
        payloads.disposals,
        symbol_key=symbol_key,
        period_key="DispositionPeriod",
        snapshot_date=snapshot_date,
    )
    available_at = max(
        payload.retrieved_at
        for payload in (
            payloads.profile,
            payloads.restrictions,
            payloads.suspended,
            payloads.attention,
            payloads.disposals,
        )
    ).isoformat()
    source_revision_hash = snapshot_revision_hash(payloads)
    rows: list[dict[str, object]] = []
    for symbol, industry_code in industries.items():
        security_id = security_ids.get((market, symbol))
        if security_id is None:
            continue
        trading_status = (
            "STOPPED"
            if symbol in stopped
            else "SUSPENDED"
            if symbol in suspended
            else "UNKNOWN"
            if symbol in excluded_intraday
            else "ACTIVE"
        )
        rows.append(
            {
                "security_id": security_id,
                "record_kind": "CURRENT_DAILY_SNAPSHOT",
                "snapshot_date": snapshot_date.isoformat(),
                "effective_from": snapshot_date.isoformat(),
                "effective_to": (snapshot_date + timedelta(days=1)).isoformat(),
                "industry_code": industry_code,
                "industry_name": None,
                "trading_status": trading_status,
                "attention_flag": symbol in attention,
                "disposal_flag": symbol in disposals,
                "altered_trading_method_flag": symbol in altered,
                # No audited current source is connected for this flag yet.
                "full_cash_delivery_flag": None,
                "periodic_auction_flag": symbol in periodic,
                "suspended_flag": (
                    None if trading_status == "UNKNOWN" else trading_status == "SUSPENDED"
                ),
                "source_id": source_id,
                "source_version": SNAPSHOT_SOURCE_VERSION,
                "source_revision_hash": source_revision_hash,
                "available_at": available_at,
            }
        )
    return NormalizedSecuritySnapshot(
        rows=tuple(rows),
        profile_date=profile_date,
        excluded_intraday_suspensions=len(excluded_intraday),
    )
