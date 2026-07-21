from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import ClassVar

import scripts.resolve_daily_research_date as resolver


class FixedDateTime(datetime):
    current: ClassVar[datetime] = datetime(2026, 7, 22, 2, 0)

    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        value = cls.current
        return value.replace(tzinfo=tz) if tz is not None else value


class FakeWriter:
    status: ClassVar[dict[str, object]] = {}
    prediction_dates: ClassVar[dict[str, str | None]] = {}

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
        return [] if value is None else [{"prediction_run_id": 1, "as_of_date": value}]


def _configure(
    *,
    aligned_date: str = "2026-07-20",
    twse_count: int = 1_079,
    tpex_count: int = 889,
    twse_prediction: str | None = "2026-07-17",
    tpex_prediction: str | None = "2026-07-17",
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
    assert 'markets=["TWSE","TPEX"]' in outputs


def test_resolver_only_publishes_the_market_that_is_behind(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure(twse_prediction="2026-07-20", tpex_prediction="2026-07-17")

    status, payload, _ = _run(tmp_path, monkeypatch)

    assert status == 0
    assert payload["markets"] == ["TPEX"]


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
