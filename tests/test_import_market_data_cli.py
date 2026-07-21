from __future__ import annotations

from datetime import date
import json

from scripts import import_market_data
from src.data.ingestion.contracts import IngestionError


class _FailingImporter:
    def __init__(self, *, settings) -> None:
        self.settings = settings

    def run(self, *, as_of_date: date, dry_run: bool):
        raise IngestionError(
            "SOURCE_MARKET_DATE_MISMATCH",
            "TWSE and TPEX daily bars are not aligned to the same trading date",
            context={
                "requested_as_of_date": as_of_date.isoformat(),
                "twse_source_date": "2026-07-21",
                "tpex_source_date": "2026-07-20",
            },
        )


class _PermanentFailingImporter:
    def __init__(self, *, settings) -> None:
        self.settings = settings

    def run(self, *, as_of_date: date, dry_run: bool):
        raise IngestionError("SOURCE_DATA_STALE", "source trading date is too old")


def test_transient_market_date_mismatch_returns_retryable_exit_code(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(import_market_data, "DailyMarketImporter", _FailingImporter)

    exit_code = import_market_data.main(["--as-of-date", "2026-07-21", "--dry-run"])

    assert exit_code == import_market_data.TRANSIENT_SOURCE_EXIT_CODE
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "context": {
            "requested_as_of_date": "2026-07-21",
            "tpex_source_date": "2026-07-20",
            "twse_source_date": "2026-07-21",
        },
        "message": "TWSE and TPEX daily bars are not aligned to the same trading date",
        "reason_code": "SOURCE_MARKET_DATE_MISMATCH",
        "status": "DEFERRED",
    }


def test_permanent_ingestion_error_remains_a_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        import_market_data,
        "DailyMarketImporter",
        _PermanentFailingImporter,
    )

    exit_code = import_market_data.main(["--as-of-date", "2026-07-21", "--dry-run"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert payload["reason_code"] == "SOURCE_DATA_STALE"
