from __future__ import annotations

from datetime import date
import json

from scripts import import_market_data
from src.data.ingestion.contracts import ImportSummary, IngestionError


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


class _SuccessfulImporter:
    def __init__(self, *, settings) -> None:
        self.settings = settings

    def run(self, *, as_of_date: date, dry_run: bool) -> ImportSummary:
        return ImportSummary(
            as_of_date=date(2026, 7, 20),
            requested_as_of_date=as_of_date,
            dry_run=dry_run,
            fetched_records={"twse_daily_bars": 1, "tpex_daily_bars": 1},
            normalized_records={"daily_bars": 2},
            excluded_records={},
            source_dates={"TWSE": "2026-07-20", "TPEX": "2026-07-20"},
        )


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


def test_transient_result_file_is_sanitized_for_recovery(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(import_market_data, "DailyMarketImporter", _FailingImporter)
    output = tmp_path / "pipeline-result.json"

    exit_code = import_market_data.main(
        [
            "--as-of-date",
            "2026-07-21",
            "--dry-run",
            "--result-output",
            str(output),
        ]
    )

    assert exit_code == import_market_data.TRANSIENT_SOURCE_EXIT_CODE
    _ = capsys.readouterr()
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "reason_code": "SOURCE_MARKET_DATE_MISMATCH",
        "requested_as_of_date": "2026-07-21",
        "schema_version": 1,
        "status": "DEFERRED",
        "tpex_source_date": "2026-07-20",
        "twse_source_date": "2026-07-21",
    }
    rendered = output.read_text(encoding="utf-8")
    assert "message" not in rendered
    assert "context" not in rendered


def test_permanent_result_file_does_not_persist_error_message(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        import_market_data,
        "DailyMarketImporter",
        _PermanentFailingImporter,
    )
    output = tmp_path / "pipeline-result.json"

    exit_code = import_market_data.main(
        [
            "--as-of-date",
            "2026-07-21",
            "--dry-run",
            "--result-output",
            str(output),
        ]
    )

    assert exit_code == 1
    _ = capsys.readouterr()
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "reason_code": "SOURCE_DATA_STALE",
        "requested_as_of_date": "2026-07-21",
        "schema_version": 1,
        "status": "FAIL",
    }
    assert "source trading date is too old" not in output.read_text(encoding="utf-8")


def test_success_result_file_contains_only_aligned_dates(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(import_market_data, "DailyMarketImporter", _SuccessfulImporter)
    output = tmp_path / "pipeline-result.json"

    exit_code = import_market_data.main(
        [
            "--as-of-date",
            "2026-07-21",
            "--dry-run",
            "--result-output",
            str(output),
        ]
    )

    assert exit_code == 0
    _ = capsys.readouterr()
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "as_of_date": "2026-07-20",
        "reason_code": "IMPORT_COMPLETED",
        "requested_as_of_date": "2026-07-21",
        "schema_version": 1,
        "status": "PASS",
        "tpex_source_date": "2026-07-20",
        "twse_source_date": "2026-07-20",
    }
