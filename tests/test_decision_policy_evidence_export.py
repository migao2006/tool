from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.data.research.decision_policy_evidence_export import (
    export_decision_policy_evidence,
)
from src.pipeline.research_decision_policy_evidence import (
    RequiredEvidenceCategory,
)


AS_OF_DATE = date(2026, 7, 17)
DECISION_AT = datetime(2026, 7, 17, 17, tzinfo=ZoneInfo("Asia/Taipei"))


class _Writer:
    def __init__(self, rows: Mapping[str, list[dict[str, object]]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        page_size: int = 1_000,
        max_rows: int = 10_000,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "table": table,
                "select": select,
                "filters": dict(filters or {}),
                "page_size": page_size,
                "max_rows": max_rows,
            }
        )
        return [dict(row) for row in self.rows.get(table, [])]


def _security_history(
    *,
    available_at: str = "2026-07-17T16:00:00+08:00",
    full_cash_delivery_flag: bool | None = False,
) -> dict[str, object]:
    return {
        "security_id": 1,
        "record_kind": "CURRENT_DAILY_SNAPSHOT",
        "snapshot_date": "2026-07-17",
        "effective_from": "2026-07-17",
        "effective_to": "2026-07-18",
        "trading_status": "ACTIVE",
        "attention_flag": False,
        "disposal_flag": False,
        "altered_trading_method_flag": False,
        "full_cash_delivery_flag": full_cash_delivery_flag,
        "periodic_auction_flag": False,
        "suspended_flag": False,
        "source_id": 4,
        "source_version": "daily-security-snapshot.v1",
        "source_revision_hash": "a" * 64,
        "available_at": available_at,
    }


def _rows(*, history: dict[str, object] | None = None) -> dict[str, list[dict[str, object]]]:
    return {
        "security_history": [history or _security_history()],
        "data_sources": [
            {
                "source_id": 4,
                "source_code": "TWSE_MOPS_SNAPSHOT",
                "is_active": True,
            }
        ],
        "prediction_runs": [
            {
                "prediction_run_id": 7,
                "as_of_date": "2026-07-17",
                "decision_at": "2026-07-17T16:30:00+08:00",
                "horizon": 5,
                "market_scope": "TWSE",
                "system_validation_status": "PASS",
                "latest_available_at": "2026-07-17T16:30:00+08:00",
                "created_at": "2026-07-17T16:31:00+08:00",
            }
        ],
        "market_predictions": [
            {
                "prediction_run_id": 7,
                "market": "TWSE",
                "calibrated_p_up": 0.55,
                "calibrated_p_neutral": 0.30,
                "calibrated_p_down": 0.15,
                "market_regime": "UPTREND_LOW_VOL_BROAD",
                "forecast_market_volatility": 0.012,
                "market_exposure_cap": 0.6,
                "model_version": "twse-market-h5-v1",
                "training_end_date": "2026-07-16",
                "created_at": "2026-07-17T16:32:00+08:00",
            }
        ],
    }


def _export(writer: _Writer) -> Any:
    return export_decision_policy_evidence(
        writer,
        market="TWSE",
        as_of_date=AS_OF_DATE,
        decision_at=DECISION_AT,
        securities={"2330": 1},
        publication_id="github:run-17:attempt-1:TWSE",
    )


def test_export_connects_safe_tradability_and_market_rows_without_position_default() -> None:
    writer = _Writer(_rows())

    snapshot = _export(writer)

    assert (
        snapshot.require(
            RequiredEvidenceCategory.TRADABILITY,
            symbol="2330",
        ).value
        is True
    )
    assert (
        snapshot.require(
            RequiredEvidenceCategory.MARKET_EXPOSURE,
            symbol=None,
        ).value
        == 0.6
    )
    position = snapshot.require(
        RequiredEvidenceCategory.POSITION_LIMITS,
        symbol="2330",
    )
    assert position.status == "MISSING"
    assert position.reason_code == "POSITION_LIMIT_PRODUCER_UNAVAILABLE"
    assert "securities" not in {str(call["table"]) for call in writer.calls}


def test_export_preserves_late_tradability_as_missing_without_using_its_value() -> None:
    writer = _Writer(
        _rows(
            history=_security_history(
                available_at="2026-07-17T18:00:00+08:00",
            )
        )
    )

    evidence = _export(writer).require(
        RequiredEvidenceCategory.TRADABILITY,
        symbol="2330",
    )

    assert evidence.status == "MISSING"
    assert evidence.value is None
    assert evidence.reason_code == "TRADABILITY_EVIDENCE_AVAILABLE_AFTER_DECISION"
    assert evidence.available_at is not None


def test_export_preserves_incomplete_tradability_as_missing() -> None:
    writer = _Writer(
        _rows(
            history=_security_history(
                full_cash_delivery_flag=None,
            )
        )
    )

    evidence = _export(writer).require(
        RequiredEvidenceCategory.TRADABILITY,
        symbol="2330",
    )

    assert evidence.status == "MISSING"
    assert evidence.value is None
    assert evidence.reason_code == "TRADABILITY_EVIDENCE_INCOMPLETE"


def test_export_does_not_accept_research_only_market_prediction_as_formal_evidence() -> None:
    rows = _rows()
    rows["prediction_runs"][0]["system_validation_status"] = "RESEARCH_ONLY"
    writer = _Writer(rows)

    evidence = _export(writer).require(
        RequiredEvidenceCategory.MARKET_EXPOSURE,
        symbol=None,
    )

    assert evidence.status == "MISSING"
    assert evidence.reason_code == "MARKET_EXPOSURE_NOT_FORMALLY_VALIDATED"


def test_export_rejects_market_prediction_published_after_the_decision() -> None:
    rows = _rows()
    rows["market_predictions"][0]["created_at"] = "2026-07-17T18:00:00+08:00"
    writer = _Writer(rows)

    evidence = _export(writer).require(
        RequiredEvidenceCategory.MARKET_EXPOSURE,
        symbol=None,
    )

    assert evidence.status == "MISSING"
    assert evidence.value is None
    assert evidence.reason_code == "MARKET_EXPOSURE_AVAILABLE_AFTER_DECISION"
    assert evidence.available_at == datetime(
        2026,
        7,
        17,
        18,
        tzinfo=ZoneInfo("Asia/Taipei"),
    )


def test_export_preserves_a_market_run_published_after_the_decision_as_late() -> None:
    rows = _rows()
    rows["prediction_runs"][0]["created_at"] = "2026-07-17T18:00:00+08:00"
    writer = _Writer(rows)

    evidence = _export(writer).require(
        RequiredEvidenceCategory.MARKET_EXPOSURE,
        symbol=None,
    )

    assert evidence.status == "MISSING"
    assert evidence.value is None
    assert evidence.reason_code == "MARKET_EXPOSURE_AVAILABLE_AFTER_DECISION"
    assert evidence.publication_id == "prediction_run:7"
    assert evidence.available_at == datetime(
        2026,
        7,
        17,
        18,
        tzinfo=ZoneInfo("Asia/Taipei"),
    )
