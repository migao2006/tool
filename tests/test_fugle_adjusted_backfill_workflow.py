from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import cast

import pytest

from scripts.backfill_fugle_adjusted import main
from src.data.ingestion.historical_fugle_adjusted_backfill_contracts import (
    FugleAdjustedBackfillSettings,
)
from src.data.providers.errors import ProviderHttpError
from src.data.providers.fugle import FugleClient
from src.data.providers.http import JsonHttpClient, TransportResponse


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "backfill-fugle-adjusted.yml"
SCRIPT = ROOT / "scripts" / "backfill_fugle_adjusted.py"


class _RateLimitedTransport:
    def __init__(self) -> None:
        self.calls: int = 0

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        del url, headers, timeout
        self.calls += 1
        return TransportResponse(status_code=429, headers={}, body=b"{}")


def test_settings_default_to_disabled_and_validate_bounded_pacing() -> None:
    settings = FugleAdjustedBackfillSettings.from_env({})

    assert not settings.enabled
    assert settings.request_budget_per_run == 25
    assert settings.pacing_seconds == 2.0

    with pytest.raises(ValueError, match="between"):
        _ = FugleAdjustedBackfillSettings.from_env(
            {"FUGLE_ADJUSTED_PACING_SECONDS": "0"}
        )


def test_disabled_cli_does_not_require_credentials_or_touch_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FUGLE_ADJUSTED_BACKFILL_ENABLED", raising=False)
    output = tmp_path / "summary.json"

    exit_code = main(
        [
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-12-31",
            "--max-tasks",
            "1",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    result = cast(
        dict[str, object],
        json.loads(output.read_text(encoding="utf-8")),
    )
    assert result["outcome"] == "DISABLED"
    assert result["attempted_tasks"] == 0
    assert result["system_status"] == "RESEARCH_ONLY"


def test_workflow_uses_one_key_two_closed_gates_and_compact_artifact() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "FUGLE_ADJUSTED_BACKFILL_ENABLED == 'true'" in workflow
    assert "FUGLE_ADJUSTED_MIGRATION_READY == 'true'" in workflow
    assert "secrets.FUGLE_API_KEY" in workflow
    assert "FINMIND_TOKEN" not in workflow
    assert "backfill_fugle_adjusted" in workflow
    assert "fugle-adjusted-summary.json" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "R2_SECRET_ACCESS_KEY" in workflow


def test_backfill_uses_one_http_attempt_and_stops_on_first_429() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    transport = _RateLimitedTransport()
    client = FugleClient(
        api_key="test-key",
        http=JsonHttpClient(
            transport=transport,
            max_attempts=1,
            retry_backoff_seconds=0.0,
        ),
    )

    assert "max_attempts=1" in script
    with pytest.raises(ProviderHttpError) as captured:
        _ = client.historical_candles(
            "2330",
            start_date="2024-01-01",
            end_date="2024-12-31",
            adjusted=True,
        )

    assert captured.value.status_code == 429
    assert transport.calls == 1
