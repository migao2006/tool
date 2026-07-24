from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import cast, ClassVar

import pytest

import scripts.resolve_daily_research_date as resolver
from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.supabase_writer import SupabaseWriter


class FixedDateTime(datetime):
    current: ClassVar[datetime] = datetime(2026, 7, 22, 2, 0)

    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        value = cls.current
        return value.replace(tzinfo=tz) if tz is not None else value


class FakeWriter:
    status: ClassVar[dict[str, object]] = {}
    prediction_dates: ClassVar[dict[str, str | None]] = {}
    prediction_complete: ClassVar[dict[str, bool]] = {}
    run_markets: ClassVar[dict[int, str]] = {}
    run_overrides: ClassVar[dict[str, dict[str, object]]] = {}
    prediction_overrides: ClassVar[dict[str, dict[str, object]]] = {}
    gate_shortfall: ClassVar[dict[str, int]] = {}

    def __init__(
        self,
        *,
        url: str | None,
        server_key: str | None,
        schema: str = "market_data",
        **_: object,
    ) -> None:
        assert url == "https://example.supabase.co"
        assert server_key == "sb_secret_test-value"
        self.schema = schema

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: dict[str, str] | None = None,
        limit: int = 1_000,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        del select, limit, offset
        if self.schema == "public":
            assert table == "home_data_status"
            return [dict(self.status)]
        assert table == "prediction_runs"
        market = str((filters or {})["market_scope"]).removeprefix("eq.")
        value = self.prediction_dates[market]
        if value is None:
            return []
        run_id = 1 if market == "TWSE" else 2
        self.run_markets[run_id] = market
        return [
            {
                "prediction_run_id": run_id,
                "as_of_date": value,
                "horizon": 5,
                "market_scope": market,
                "system_validation_status": "RESEARCH_ONLY",
                "candidate_count": 0,
                "watch_count": 0,
                "no_trade_count": 0,
                "policy_input_missing_count": 500,
                "policy_validation_failed_count": 0,
                "policy_hard_fail_count": 0,
                "hard_fail_count": 0,
                **self.run_overrides.get(market, {}),
            }
        ]

    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: dict[str, str] | None = None,
        page_size: int = 1_000,
        max_rows: int = 10_000,
    ) -> list[dict[str, object]]:
        del select, page_size, max_rows
        assert table == "stock_predictions"
        run_id = int(str((filters or {})["prediction_run_id"]).removeprefix("eq."))
        market = self.run_markets[run_id]
        return [
            {
                "stock_prediction_id": run_id * 1_000 + index,
                "market": market,
                "decision": None,
                "decision_policy_status": "MISSING_REQUIRED_DATA",
                "data_quality_status": "WARN",
                **self.prediction_overrides.get(market, {}),
            }
            for index in range(500)
        ]

    def count_rows(
        self,
        table: str,
        *,
        filters: dict[str, str] | None = None,
    ) -> int:
        assert table == "decision_gate_results"
        raw_ids = str((filters or {})["stock_prediction_id"])
        first_id = int(raw_ids.removeprefix("in.(").split(",", 1)[0])
        run_id = first_id // 1_000
        market = self.run_markets[run_id]
        batch_size = raw_ids.count(",") + 1
        if not self.prediction_complete[market]:
            return 0
        return max(0, batch_size * 8 - self.gate_shortfall.get(market, 0))


def _configure(
    *,
    aligned_date: str = "2026-07-20",
    twse_count: int = 1_079,
    tpex_count: int = 889,
    twse_prediction: str | None = "2026-07-17",
    tpex_prediction: str | None = "2026-07-17",
    twse_complete: bool = True,
    tpex_complete: bool = True,
) -> None:
    FakeWriter.status = {
        "status_key": "latest",
        "as_of_date": aligned_date,
        "daily_bars_latest_date": aligned_date,
        "twse_daily_bars_latest_count": twse_count,
        "tpex_daily_bars_latest_count": tpex_count,
        "updated_at": f"{aligned_date}T14:00:00+00:00",
    }
    FakeWriter.prediction_dates = {
        "TWSE": twse_prediction,
        "TPEX": tpex_prediction,
    }
    FakeWriter.prediction_complete = {
        "TWSE": twse_complete,
        "TPEX": tpex_complete,
    }
    FakeWriter.run_markets = {}
    FakeWriter.run_overrides = {}
    FakeWriter.prediction_overrides = {}
    FakeWriter.gate_shortfall = {}


def _run(
    tmp_path: Path,
    monkeypatch,
    *,
    extra: list[str] | None = None,
) -> tuple[int, dict[str, object], str]:
    monkeypatch.setattr(resolver, "SupabaseWriter", FakeWriter)
    monkeypatch.setattr(resolver, "datetime", FixedDateTime)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test-value")
    output = tmp_path / "resolution.json"
    github_output = tmp_path / "github-output.txt"
    argv = ["--output", str(output), "--github-output", str(github_output)]
    if extra:
        argv.extend(extra)
    status = resolver.main(argv)
    payload = json.loads(output.read_text(encoding="utf-8"))
    rendered_outputs = github_output.read_text(encoding="utf-8") if github_output.exists() else ""
    return status, payload, rendered_outputs


def test_resolver_selects_both_markets_missing_the_aligned_date(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure()

    status, payload, outputs = _run(tmp_path, monkeypatch)

    assert status == 0
    assert payload["should_run"] is True
    assert payload["as_of_date"] == "2026-07-20"
    assert payload["markets"] == ["TWSE", "TPEX"]
    assert payload["schema_version"] == 1
    assert payload["validated_production_snapshots"] == {
        "TWSE": {
            "as_of_date": "2026-07-17",
            "prediction_run_id": 1,
            "prediction_count": 500,
            "decision_gate_count": 4_000,
            "system_status": "RESEARCH_ONLY",
        },
        "TPEX": {
            "as_of_date": "2026-07-17",
            "prediction_run_id": 2,
            "prediction_count": 500,
            "decision_gate_count": 4_000,
            "system_status": "RESEARCH_ONLY",
        },
    }
    assert 'markets=["TWSE","TPEX"]' in outputs


def test_resolver_only_publishes_the_market_that_is_behind(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure(twse_prediction="2026-07-20", tpex_prediction="2026-07-17")

    status, payload, _ = _run(tmp_path, monkeypatch)

    assert status == 0
    assert payload["markets"] == ["TPEX"]


def test_resolver_republishes_a_latest_dated_but_incomplete_market(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure(
        twse_prediction="2026-07-20",
        tpex_prediction="2026-07-20",
        twse_complete=False,
    )

    status, payload, _ = _run(tmp_path, monkeypatch)

    assert status == 0
    assert payload["latest_prediction_dates"] == {
        "TWSE": None,
        "TPEX": "2026-07-20",
    }
    assert payload["markets"] == ["TWSE"]


@pytest.mark.parametrize(
    ("run_override", "prediction_override", "gate_shortfall"),
    [
        ({"policy_input_missing_count": 499}, {}, 0),
        ({}, {"decision": "WATCH"}, 0),
        ({}, {"decision_policy_status": "EVALUATED"}, 0),
        (
            {},
            {
                "decision": "NO_TRADE",
                "decision_policy_status": "EVALUATED",
                "data_quality_status": "WARN",
            },
            0,
        ),
        ({}, {"data_quality_status": "HARD_FAIL"}, 0),
        ({}, {}, 1),
    ],
)
def test_latest_prediction_requires_every_production_completion_gate(
    run_override: dict[str, object],
    prediction_override: dict[str, object],
    gate_shortfall: int,
) -> None:
    _configure(twse_prediction="2026-07-20")
    FakeWriter.run_overrides["TWSE"] = run_override
    FakeWriter.prediction_overrides["TWSE"] = prediction_override
    FakeWriter.gate_shortfall["TWSE"] = gate_shortfall
    writer = FakeWriter(
        url="https://example.supabase.co",
        server_key="sb_secret_test-value",
    )

    assert resolver._latest_prediction_date(cast(SupabaseWriter, writer), "TWSE") is None


def test_resolution_retries_only_transient_connection_errors() -> None:
    attempts = 0
    delays: list[float] = []
    expected = {"status": "PASS", "should_run": False}

    def resolve_once() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise IngestionError(
                "SUPABASE_CONNECTION_ERROR",
                "Supabase read request could not be completed",
            )
        return expected

    result = resolver._resolve_with_connection_retry(
        resolve_once,
        sleeper=delays.append,
    )

    assert result == expected
    assert attempts == 3
    assert delays == [1.0, 2.0]


def test_resolution_connection_retry_exhaustion_preserves_reason_code() -> None:
    attempts = 0
    delays: list[float] = []

    def resolve_once() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise IngestionError(
            "SUPABASE_CONNECTION_ERROR",
            "Supabase read request could not be completed",
        )

    with pytest.raises(IngestionError) as captured:
        resolver._resolve_with_connection_retry(
            resolve_once,
            sleeper=delays.append,
        )

    assert captured.value.reason_code == "SUPABASE_CONNECTION_ERROR"
    assert attempts == 3
    assert delays == [1.0, 2.0]


def test_resolution_does_not_retry_a_validation_failure() -> None:
    attempts = 0
    delays: list[float] = []

    def resolve_once() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise ValueError("HOME_DATA_STATUS_UNAVAILABLE")

    with pytest.raises(ValueError, match="HOME_DATA_STATUS_UNAVAILABLE"):
        resolver._resolve_with_connection_retry(
            resolve_once,
            sleeper=delays.append,
        )

    assert attempts == 1
    assert delays == []


def test_long_market_closure_is_a_clean_noop_when_snapshots_are_current(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FixedDateTime.current = datetime(2026, 2, 23, 12, 0)
    _configure(
        aligned_date="2026-02-13",
        twse_prediction="2026-02-13",
        tpex_prediction="2026-02-13",
    )

    status, payload, outputs = _run(tmp_path, monkeypatch, extra=["--max-age-days", "7"])

    assert status == 0
    assert payload["source_age_days"] == 10
    assert payload["should_run"] is False
    assert payload["markets"] == []
    assert "should_run=false" in outputs


def test_stale_source_blocks_a_missing_snapshot_with_stable_reason_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FixedDateTime.current = datetime(2026, 2, 23, 12, 0)
    _configure(
        aligned_date="2026-02-13",
        twse_prediction="2026-02-13",
        tpex_prediction="2026-02-12",
    )

    status, payload, _ = _run(tmp_path, monkeypatch, extra=["--max-age-days", "7"])

    assert status == 1
    assert payload["reason_codes"] == ["DAILY_RESEARCH_SOURCE_DATE_OUTSIDE_ALLOWED_AGE"]


def test_coverage_gate_only_applies_to_markets_that_need_publication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FixedDateTime.current = datetime(2026, 7, 22, 2, 0)
    _configure(
        twse_count=100,
        tpex_count=889,
        twse_prediction="2026-07-20",
        tpex_prediction="2026-07-17",
    )

    status, payload, _ = _run(tmp_path, monkeypatch)

    assert status == 0
    assert payload["markets"] == ["TPEX"]


def test_requested_date_after_aligned_data_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure()

    status, payload, _ = _run(
        tmp_path,
        monkeypatch,
        extra=["--as-of-date", "2026-07-21"],
    )

    assert status == 1
    assert payload["reason_codes"] == ["REQUESTED_DAILY_BAR_DATE_NOT_AVAILABLE"]
