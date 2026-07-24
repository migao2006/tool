"""Strict evidence composition for the owner-triggered full daily update."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import re
from typing import cast

from src.pipeline.daily_research_publish_contract import (
    DAILY_RESEARCH_GATES_PER_PREDICTION,
    MIN_DAILY_RESEARCH_PREDICTIONS,
)


MARKETS = ("TWSE", "TPEX")
MAX_IMPORT_RESULT_BYTES = 4_096
MAX_DAILY_RESULT_BYTES = 32_768
_SAFE_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SHA = re.compile(r"[0-9a-f]{40}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_ACTOR = re.compile(r"[A-Za-z0-9-]{1,39}")
_JOB_RESULTS = frozenset({"success", "failure", "cancelled", "skipped"})
_IMPORT_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "reason_code",
        "requested_as_of_date",
        "twse_source_date",
        "tpex_source_date",
        "as_of_date",
    }
)
_RESOLUTION_SUCCESS_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "should_run",
        "as_of_date",
        "aligned_daily_bar_date",
        "source_age_days",
        "markets",
        "daily_bar_counts",
        "latest_prediction_dates",
        "validated_production_snapshots",
    }
)
_VERIFICATION_SUCCESS_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "verified_at",
        "target_environment",
        "market",
        "as_of_date",
        "prediction_run_id",
        "prediction_count",
        "decision_gate_count",
        "system_status",
    }
)


class EvidenceContractError(RuntimeError):
    """A fail-closed artifact or cross-artifact contract error."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ImportResult:
    status: str
    reason_code: str
    requested_as_of_date: str | None
    twse_source_date: str | None
    tpex_source_date: str | None
    as_of_date: str | None


@dataclass(frozen=True)
class ValidatedSnapshot:
    market: str
    as_of_date: str
    prediction_run_id: int
    prediction_count: int
    decision_gate_count: int
    system_status: str = "RESEARCH_ONLY"

    def to_payload(self, *, evidence_source: str) -> dict[str, object]:
        return {
            "as_of_date": self.as_of_date,
            "prediction_run_id": self.prediction_run_id,
            "prediction_count": self.prediction_count,
            "decision_gate_count": self.decision_gate_count,
            "system_status": self.system_status,
            "evidence_source": evidence_source,
            "complete": True,
        }


@dataclass(frozen=True)
class ResolutionResult:
    target_as_of_date: str
    aligned_daily_bar_date: str
    source_age_days: int
    required_markets: tuple[str, ...]
    daily_bar_counts: Mapping[str, int]
    snapshots: Mapping[str, ValidatedSnapshot | None]


def _error(reason_code: str) -> EvidenceContractError:
    return EvidenceContractError(reason_code)


def _json_object(
    raw: bytes,
    *,
    maximum_bytes: int,
    too_large_code: str,
    invalid_json_code: str,
    invalid_schema_code: str,
) -> dict[str, object]:
    if len(raw) > maximum_bytes:
        raise _error(too_large_code)
    try:
        value = cast(object, json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error(invalid_json_code) from error
    if not isinstance(value, dict):
        raise _error(invalid_schema_code)
    return cast(dict[str, object], value)


def _iso_date(value: object, reason_code: str) -> str:
    if not isinstance(value, str):
        raise _error(reason_code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise _error(reason_code) from error
    if parsed.isoformat() != value:
        raise _error(reason_code)
    return value


def _optional_iso_date(value: object, reason_code: str) -> str | None:
    if value is None:
        return None
    return _iso_date(value, reason_code)


def _non_negative_integer(value: object, reason_code: str) -> int:
    if type(value) is not int or value < 0:
        raise _error(reason_code)
    return value


def _positive_integer(value: object, reason_code: str) -> int:
    parsed = _non_negative_integer(value, reason_code)
    if parsed == 0:
        raise _error(reason_code)
    return parsed


def _safe_reason(value: object, reason_code: str) -> str:
    if not isinstance(value, str) or not _SAFE_REASON_CODE.fullmatch(value):
        raise _error(reason_code)
    return value


def _single_reason(value: object, reason_code: str) -> str:
    if not isinstance(value, list) or len(value) != 1:
        raise _error(reason_code)
    return _safe_reason(value[0], reason_code)


def _timestamp(value: object, reason_code: str) -> str:
    if not isinstance(value, str) or len(value) > 64:
        raise _error(reason_code)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise _error(reason_code) from error
    if parsed.tzinfo is None:
        raise _error(reason_code)
    return value


def parse_import_result(raw: bytes) -> ImportResult:
    """Parse the existing sanitized import result without weakening recovery."""

    payload = _json_object(
        raw,
        maximum_bytes=MAX_IMPORT_RESULT_BYTES,
        too_large_code="IMPORT_RESULT_TOO_LARGE",
        invalid_json_code="INVALID_IMPORT_RESULT_JSON",
        invalid_schema_code="INVALID_IMPORT_RESULT_SCHEMA",
    )
    if not set(payload).issubset(_IMPORT_RESULT_KEYS):
        raise _error("INVALID_IMPORT_RESULT_SCHEMA")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise _error("INVALID_IMPORT_RESULT_SCHEMA")
    status = payload.get("status")
    if status not in {"PASS", "DEFERRED", "FAIL"}:
        raise _error("INVALID_IMPORT_RESULT_STATUS")
    reason_code = _safe_reason(
        payload.get("reason_code"),
        "INVALID_IMPORT_RESULT_REASON",
    )
    requested = _optional_iso_date(
        payload.get("requested_as_of_date"),
        "INVALID_IMPORT_RESULT_REQUESTED_DATE",
    )
    twse = _optional_iso_date(
        payload.get("twse_source_date"),
        "INVALID_IMPORT_RESULT_SOURCE_DATE",
    )
    tpex = _optional_iso_date(
        payload.get("tpex_source_date"),
        "INVALID_IMPORT_RESULT_SOURCE_DATE",
    )
    as_of_date = _optional_iso_date(
        payload.get("as_of_date"),
        "INVALID_IMPORT_RESULT_AS_OF_DATE",
    )
    if requested is None:
        raise _error("INVALID_IMPORT_RESULT_REQUESTED_DATE")
    if status != "PASS" and as_of_date is not None:
        raise _error("INVALID_IMPORT_RESULT_AS_OF_DATE")
    if (
        status == "PASS"
        and (
            reason_code != "IMPORT_COMPLETED"
            or as_of_date is None
            or twse is None
            or tpex is None
            or twse != as_of_date
            or tpex != as_of_date
        )
    ):
        raise _error("INVALID_IMPORT_RESULT_SUCCESS")
    if (
        status == "DEFERRED"
        and (
            reason_code != "SOURCE_MARKET_DATE_MISMATCH"
            or twse is None
            or tpex is None
            or twse == tpex
        )
    ):
        raise _error("INVALID_IMPORT_RESULT_MISMATCH")
    return ImportResult(
        status=cast(str, status),
        reason_code=reason_code,
        requested_as_of_date=requested,
        twse_source_date=twse,
        tpex_source_date=tpex,
        as_of_date=as_of_date,
    )


def _parse_snapshot(value: object, market: str) -> ValidatedSnapshot | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "as_of_date",
        "prediction_run_id",
        "prediction_count",
        "decision_gate_count",
        "system_status",
    }:
        raise _error("INVALID_RESOLUTION_SNAPSHOT_SCHEMA")
    snapshot = cast(dict[str, object], value)
    as_of_date = _iso_date(
        snapshot.get("as_of_date"),
        "INVALID_RESOLUTION_SNAPSHOT_DATE",
    )
    run_id = _positive_integer(
        snapshot.get("prediction_run_id"),
        "INVALID_RESOLUTION_SNAPSHOT_RUN",
    )
    prediction_count = _positive_integer(
        snapshot.get("prediction_count"),
        "INVALID_RESOLUTION_SNAPSHOT_COUNTS",
    )
    gate_count = _positive_integer(
        snapshot.get("decision_gate_count"),
        "INVALID_RESOLUTION_SNAPSHOT_COUNTS",
    )
    if (
        snapshot.get("system_status") != "RESEARCH_ONLY"
        or prediction_count < MIN_DAILY_RESEARCH_PREDICTIONS[market]
        or gate_count != prediction_count * DAILY_RESEARCH_GATES_PER_PREDICTION
    ):
        raise _error("INVALID_RESOLUTION_SNAPSHOT_COUNTS")
    return ValidatedSnapshot(
        market=market,
        as_of_date=as_of_date,
        prediction_run_id=run_id,
        prediction_count=prediction_count,
        decision_gate_count=gate_count,
    )


def parse_resolution_result(raw: bytes) -> ResolutionResult:
    """Parse one resolver result and preserve its missing-market decision."""

    payload = _json_object(
        raw,
        maximum_bytes=MAX_DAILY_RESULT_BYTES,
        too_large_code="RESOLUTION_RESULT_TOO_LARGE",
        invalid_json_code="INVALID_RESOLUTION_RESULT_JSON",
        invalid_schema_code="INVALID_RESOLUTION_RESULT_SCHEMA",
    )
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise _error("INVALID_RESOLUTION_RESULT_SCHEMA")
    if payload.get("status") == "FAIL":
        raise _error(
            _single_reason(
                payload.get("reason_codes"),
                "INVALID_RESOLUTION_RESULT_REASON",
            )
        )
    if set(payload) != _RESOLUTION_SUCCESS_KEYS or payload.get("status") != "PASS":
        raise _error("INVALID_RESOLUTION_RESULT_SCHEMA")
    if type(payload.get("should_run")) is not bool:
        raise _error("INVALID_RESOLUTION_RESULT_SCHEMA")
    target = _iso_date(payload.get("as_of_date"), "INVALID_RESOLUTION_TARGET_DATE")
    aligned = _iso_date(
        payload.get("aligned_daily_bar_date"),
        "INVALID_RESOLUTION_ALIGNED_DATE",
    )
    if target > aligned:
        raise _error("INVALID_RESOLUTION_TARGET_DATE")
    source_age_days = _non_negative_integer(
        payload.get("source_age_days"),
        "INVALID_RESOLUTION_SOURCE_AGE",
    )
    raw_markets = payload.get("markets")
    if (
        not isinstance(raw_markets, list)
        or any(market not in MARKETS for market in raw_markets)
        or len(set(cast(list[object], raw_markets))) != len(raw_markets)
        or raw_markets != [market for market in MARKETS if market in raw_markets]
    ):
        raise _error("INVALID_RESOLUTION_MARKETS")
    required_markets = tuple(cast(list[str], raw_markets))
    if cast(bool, payload["should_run"]) != bool(required_markets):
        raise _error("INVALID_RESOLUTION_MARKETS")
    raw_counts = payload.get("daily_bar_counts")
    raw_dates = payload.get("latest_prediction_dates")
    raw_snapshots = payload.get("validated_production_snapshots")
    if (
        not isinstance(raw_counts, dict)
        or set(raw_counts) != set(MARKETS)
        or not isinstance(raw_dates, dict)
        or set(raw_dates) != set(MARKETS)
        or not isinstance(raw_snapshots, dict)
        or set(raw_snapshots) != set(MARKETS)
    ):
        raise _error("INVALID_RESOLUTION_MARKET_EVIDENCE")
    counts = {
        market: _non_negative_integer(
            raw_counts.get(market),
            "INVALID_RESOLUTION_DAILY_BAR_COUNTS",
        )
        for market in MARKETS
    }
    snapshots = {
        market: _parse_snapshot(raw_snapshots.get(market), market)
        for market in MARKETS
    }
    for market in MARKETS:
        snapshot = snapshots[market]
        rendered_date = _optional_iso_date(
            raw_dates.get(market),
            "INVALID_RESOLUTION_SNAPSHOT_DATE",
        )
        if rendered_date != (snapshot.as_of_date if snapshot is not None else None):
            raise _error("INVALID_RESOLUTION_MARKET_EVIDENCE")
        is_missing = snapshot is None or snapshot.as_of_date < target
        if is_missing != (market in required_markets):
            raise _error("INVALID_RESOLUTION_MARKETS")
    return ResolutionResult(
        target_as_of_date=target,
        aligned_daily_bar_date=aligned,
        source_age_days=source_age_days,
        required_markets=required_markets,
        daily_bar_counts=counts,
        snapshots=snapshots,
    )


def parse_production_verification(
    raw: bytes,
    *,
    expected_market: str,
    expected_as_of_date: str,
) -> ValidatedSnapshot:
    """Parse only the verifier output, never an untrusted publish report."""

    if expected_market not in MARKETS:
        raise _error("INVALID_PRODUCTION_VERIFICATION_MARKET")
    expected_date = _iso_date(
        expected_as_of_date,
        "INVALID_PRODUCTION_VERIFICATION_DATE",
    )
    payload = _json_object(
        raw,
        maximum_bytes=MAX_DAILY_RESULT_BYTES,
        too_large_code="PRODUCTION_VERIFICATION_TOO_LARGE",
        invalid_json_code="INVALID_PRODUCTION_VERIFICATION_JSON",
        invalid_schema_code="INVALID_PRODUCTION_VERIFICATION_SCHEMA",
    )
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise _error("INVALID_PRODUCTION_VERIFICATION_SCHEMA")
    if payload.get("status") == "FAIL":
        raise _error(
            _single_reason(
                payload.get("reason_codes"),
                "INVALID_PRODUCTION_VERIFICATION_REASON",
            )
        )
    if set(payload) != _VERIFICATION_SUCCESS_KEYS or payload.get("status") != "PASS":
        raise _error("INVALID_PRODUCTION_VERIFICATION_SCHEMA")
    _ = _timestamp(
        payload.get("verified_at"),
        "INVALID_PRODUCTION_VERIFICATION_TIMESTAMP",
    )
    market = payload.get("market")
    as_of_date = _iso_date(
        payload.get("as_of_date"),
        "INVALID_PRODUCTION_VERIFICATION_DATE",
    )
    run_id = _positive_integer(
        payload.get("prediction_run_id"),
        "INVALID_PRODUCTION_VERIFICATION_RUN",
    )
    prediction_count = _positive_integer(
        payload.get("prediction_count"),
        "INVALID_PRODUCTION_VERIFICATION_COUNTS",
    )
    gate_count = _positive_integer(
        payload.get("decision_gate_count"),
        "INVALID_PRODUCTION_VERIFICATION_COUNTS",
    )
    if (
        market != expected_market
        or as_of_date != expected_date
        or payload.get("target_environment") != "production"
        or payload.get("system_status") != "RESEARCH_ONLY"
        or prediction_count < MIN_DAILY_RESEARCH_PREDICTIONS[expected_market]
        or gate_count != prediction_count * DAILY_RESEARCH_GATES_PER_PREDICTION
    ):
        raise _error("INVALID_PRODUCTION_VERIFICATION_SCOPE")
    return ValidatedSnapshot(
        market=expected_market,
        as_of_date=as_of_date,
        prediction_run_id=run_id,
        prediction_count=prediction_count,
        decision_gate_count=gate_count,
    )


def _validated_trigger(
    *,
    actor: str,
    repository: str,
    branch: str,
    sha: str,
    run_id: int,
    run_attempt: int,
) -> dict[str, object]:
    if (
        not _ACTOR.fullmatch(actor)
        or not _REPOSITORY.fullmatch(repository)
        or branch != "main"
        or not _SHA.fullmatch(sha)
        or type(run_id) is not int
        or run_id <= 0
        or type(run_attempt) is not int
        or run_attempt <= 0
    ):
        raise _error("INVALID_MANUAL_TRIGGER_IDENTITY")
    return {
        "actor": actor,
        "event": "workflow_dispatch",
        "repository": repository,
        "branch": branch,
        "head_sha": sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }


def _job_result(value: str) -> str:
    if value not in _JOB_RESULTS:
        raise _error("INVALID_MANUAL_JOB_RESULT")
    return value


def _market_state(
    snapshot: ValidatedSnapshot | None,
    *,
    evidence_source: str,
    action: str,
    before_as_of_date: str | None,
) -> dict[str, object]:
    return {
        "action": action,
        "before_as_of_date": before_as_of_date,
        "final_snapshot": (
            snapshot.to_payload(evidence_source=evidence_source)
            if snapshot is not None
            else None
        ),
    }


def _snapshot_date(snapshot: ValidatedSnapshot | None) -> str | None:
    return snapshot.as_of_date if snapshot is not None else None


def summarize_manual_full_update(
    *,
    import_raw: bytes | None,
    resolution_raw: bytes | None,
    production_raw: Mapping[str, bytes | None],
    actor: str,
    repository: str,
    branch: str,
    sha: str,
    run_id: int,
    run_attempt: int,
    requested_as_of_date: str | None,
    dry_run: bool,
    publish_production: bool,
    production_publish_enabled: bool,
    preflight_result: str,
    import_job_result: str,
    research_job_result: str,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Compose one deterministic, fail-closed operator and recovery summary."""

    now = generated_at or datetime.now(timezone.utc)
    normalized_requested = requested_as_of_date or None
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "FAIL",
        "outcome": "FAILED",
        "reason_code": "MANUAL_FULL_UPDATE_SUMMARY_FAILED",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "trigger": None,
        "inputs": {
            "requested_as_of_date": normalized_requested,
            "dry_run": dry_run,
            "publish_production": publish_production,
        },
        "import": None,
        "resolution": None,
        "production": {
            "requested": publish_production,
            "changed": False,
            "published_markets": [],
            "final_as_of_date": None,
            "prediction_and_decision_gate_complete": False,
            "markets": {
                market: _market_state(
                    None,
                    evidence_source="NONE",
                    action="NOT_VERIFIED",
                    before_as_of_date=None,
                )
                for market in MARKETS
            },
        },
    }
    try:
        payload["trigger"] = _validated_trigger(
            actor=actor,
            repository=repository,
            branch=branch,
            sha=sha,
            run_id=run_id,
            run_attempt=run_attempt,
        )
        requested = (
            _iso_date(normalized_requested, "INVALID_MANUAL_REQUESTED_DATE")
            if normalized_requested
            else None
        )
        if _job_result(preflight_result) != "success":
            raise _error("MANUAL_PREFLIGHT_FAILED")
        if import_raw is None:
            raise _error("IMPORT_RESULT_MISSING")
        imported = parse_import_result(import_raw)
        payload["import"] = {
            "status": imported.status,
            "reason_code": imported.reason_code,
            "requested_as_of_date": imported.requested_as_of_date,
            "as_of_date": imported.as_of_date,
            "source_dates": {
                "TWSE": imported.twse_source_date,
                "TPEX": imported.tpex_source_date,
            },
        }
        if imported.status != "PASS":
            raise _error(imported.reason_code)
        if _job_result(import_job_result) != "success":
            raise _error("MARKET_IMPORT_WORKFLOW_FAILED")
        if resolution_raw is None:
            raise _error("RESOLUTION_RESULT_MISSING")
        resolution = parse_resolution_result(resolution_raw)
        if requested is not None and resolution.target_as_of_date != requested:
            raise _error("MANUAL_REQUESTED_DATE_NOT_RESOLVED")
        if (
            not dry_run
            and imported.as_of_date != resolution.aligned_daily_bar_date
        ):
            raise _error("IMPORT_RESOLUTION_DATE_MISMATCH")
        payload["resolution"] = {
            "status": "PASS",
            "target_as_of_date": resolution.target_as_of_date,
            "aligned_daily_bar_date": resolution.aligned_daily_bar_date,
            "source_age_days": resolution.source_age_days,
            "required_markets": list(resolution.required_markets),
            "daily_bar_counts": dict(resolution.daily_bar_counts),
        }
        final_snapshots = dict(resolution.snapshots)
        market_states = {
            market: _market_state(
                resolution.snapshots[market],
                evidence_source="RESOLUTION",
                action=(
                    "UPDATE_REQUIRED"
                    if market in resolution.required_markets
                    else "NO_CHANGE_REQUIRED"
                ),
                before_as_of_date=_snapshot_date(resolution.snapshots[market]),
            )
            for market in MARKETS
        }
        available_verifications = {
            market for market in MARKETS if production_raw.get(market) is not None
        }
        verifications: dict[str, ValidatedSnapshot] = {}
        for market in available_verifications:
            verifications[market] = parse_production_verification(
                cast(bytes, production_raw.get(market)),
                expected_market=market,
                expected_as_of_date=resolution.target_as_of_date,
            )
        research_result = _job_result(research_job_result)
        if research_result != "success":
            raise _error("DAILY_RESEARCH_WORKFLOW_FAILED")

        required = set(resolution.required_markets)
        if dry_run:
            if available_verifications:
                raise _error("UNEXPECTED_PRODUCTION_VERIFICATION")
            outcome = "DRY_RUN"
            reason = "DRY_RUN_COMPLETED"
            for market in MARKETS:
                market_states[market]["action"] = "DRY_RUN_NO_WRITE"
        elif not required:
            if available_verifications:
                raise _error("UNEXPECTED_PRODUCTION_VERIFICATION")
            if any(
                resolution.snapshots[market] is None
                or cast(
                    ValidatedSnapshot,
                    resolution.snapshots[market],
                ).as_of_date
                < resolution.target_as_of_date
                for market in MARKETS
            ):
                raise _error("INVALID_NO_OP_PRODUCTION_STATE")
            outcome = "NO_CHANGE_REQUIRED"
            reason = "ALREADY_CURRENT"
        elif not publish_production:
            if available_verifications:
                raise _error("UNEXPECTED_PRODUCTION_VERIFICATION")
            outcome = "STAGING_VERIFIED"
            reason = "PRODUCTION_SKIPPED_BY_INPUT"
            for market in resolution.required_markets:
                market_states[market]["action"] = "STAGING_VERIFIED_ONLY"
        else:
            if not production_publish_enabled:
                raise _error("PRODUCTION_PUBLISH_GATE_DISABLED")
            if available_verifications != required:
                raise _error("PRODUCTION_VERIFICATION_SET_MISMATCH")
            for market in resolution.required_markets:
                verified = verifications[market]
                final_snapshots[market] = verified
                market_states[market] = _market_state(
                    verified,
                    evidence_source="PRODUCTION_VERIFICATION",
                    action="PUBLISHED_AND_VERIFIED",
                    before_as_of_date=_snapshot_date(
                        resolution.snapshots[market]
                    ),
                )
            if any(
                final_snapshots[market] is None
                or cast(ValidatedSnapshot, final_snapshots[market]).as_of_date
                < resolution.target_as_of_date
                for market in MARKETS
            ):
                raise _error("FINAL_PRODUCTION_STATE_INCOMPLETE")
            outcome = "PRODUCTION_UPDATED"
            reason = "PRODUCTION_PUBLISHED_AND_VERIFIED"

        final_dates = {
            cast(ValidatedSnapshot, snapshot).as_of_date
            for snapshot in final_snapshots.values()
            if snapshot is not None
        }
        all_complete = all(final_snapshots[market] is not None for market in MARKETS)
        production_payload = cast(dict[str, object], payload["production"])
        production_payload.update(
            {
                "changed": outcome == "PRODUCTION_UPDATED",
                "published_markets": (
                    list(resolution.required_markets)
                    if outcome == "PRODUCTION_UPDATED"
                    else []
                ),
                "final_as_of_date": (
                    next(iter(final_dates))
                    if len(final_dates) == 1 and all_complete
                    else None
                ),
                "prediction_and_decision_gate_complete": all_complete,
                "markets": market_states,
            }
        )
        payload.update(
            {
                "status": "PASS",
                "outcome": outcome,
                "reason_code": reason,
            }
        )
    except EvidenceContractError as error:
        payload["reason_code"] = error.reason_code
    return payload


def render_manual_full_update_markdown(payload: Mapping[str, object]) -> str:
    """Render only typed, sanitized summary fields."""

    trigger = payload.get("trigger")
    inputs = payload.get("inputs")
    imported = payload.get("import")
    resolution = payload.get("resolution")
    production = payload.get("production")
    trigger_map = cast(Mapping[str, object], trigger) if isinstance(trigger, Mapping) else {}
    inputs_map = cast(Mapping[str, object], inputs) if isinstance(inputs, Mapping) else {}
    import_map = cast(Mapping[str, object], imported) if isinstance(imported, Mapping) else {}
    resolution_map = (
        cast(Mapping[str, object], resolution)
        if isinstance(resolution, Mapping)
        else {}
    )
    production_map = (
        cast(Mapping[str, object], production)
        if isinstance(production, Mapping)
        else {}
    )
    source_dates = import_map.get("source_dates")
    source_map = (
        cast(Mapping[str, object], source_dates)
        if isinstance(source_dates, Mapping)
        else {}
    )
    market_payload = production_map.get("markets")
    markets_map = (
        cast(Mapping[str, object], market_payload)
        if isinstance(market_payload, Mapping)
        else {}
    )

    def shown(value: object) -> str:
        if value is None or value == "":
            return "N/A"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    required = resolution_map.get("required_markets")
    required_markets = set(required) if isinstance(required, list) else set()
    rows: list[str] = []
    for market in MARKETS:
        raw_state = markets_map.get(market)
        state = (
            cast(Mapping[str, object], raw_state)
            if isinstance(raw_state, Mapping)
            else {}
        )
        raw_snapshot = state.get("final_snapshot")
        snapshot = (
            cast(Mapping[str, object], raw_snapshot)
            if isinstance(raw_snapshot, Mapping)
            else {}
        )
        rows.append(
            "| "
            + " | ".join(
                (
                    market,
                    shown(source_map.get(market)),
                    shown(state.get("before_as_of_date")),
                    "yes" if market in required_markets else "no",
                    shown(state.get("action")),
                    shown(snapshot.get("as_of_date")),
                    shown(snapshot.get("prediction_count")),
                    shown(snapshot.get("decision_gate_count")),
                    shown(snapshot.get("complete")),
                )
            )
            + " |"
        )
    return "\n".join(
        (
            "## Manual full update",
            "",
            f"- Status: `{shown(payload.get('status'))}`",
            f"- Outcome: `{shown(payload.get('outcome'))}`",
            f"- Reason: `{shown(payload.get('reason_code'))}`",
            (
                "- Trigger: "
                f"`{shown(trigger_map.get('repository'))}` / "
                f"`{shown(trigger_map.get('branch'))}` / "
                f"`{shown(trigger_map.get('head_sha'))}`"
            ),
            (
                "- Run: "
                f"`{shown(trigger_map.get('run_id'))}` attempt "
                f"`{shown(trigger_map.get('run_attempt'))}` by "
                f"`{shown(trigger_map.get('actor'))}`"
            ),
            (
                "- Inputs: "
                f"`dry_run={shown(inputs_map.get('dry_run'))}`, "
                f"`publish_production={shown(inputs_map.get('publish_production'))}`, "
                f"`as_of_date={shown(inputs_map.get('requested_as_of_date'))}`"
            ),
            (
                "- Resolved target / aligned market date: "
                f"`{shown(resolution_map.get('target_as_of_date'))}` / "
                f"`{shown(resolution_map.get('aligned_daily_bar_date'))}`"
            ),
            (
                "- Markets requiring update: "
                f"`{shown(','.join(cast(list[str], required)) if isinstance(required, list) else None)}`"
            ),
            f"- Production changed: `{shown(production_map.get('changed'))}`",
            (
                "- Final Production as_of_date: "
                f"`{shown(production_map.get('final_as_of_date'))}`"
            ),
            (
                "- Prediction and decision-gate completeness: "
                f"`{shown(production_map.get('prediction_and_decision_gate_complete'))}`"
            ),
            "",
            "| Market | Source date | Before valid date | Required | Production action | "
            "Final valid date | Predictions | Decision gates | Complete |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |",
            *rows,
            "",
        )
    )


__all__ = [
    "EvidenceContractError",
    "ImportResult",
    "MARKETS",
    "ResolutionResult",
    "ValidatedSnapshot",
    "parse_import_result",
    "parse_production_verification",
    "parse_resolution_result",
    "render_manual_full_update_markdown",
    "summarize_manual_full_update",
]
