from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_WORKFLOW = ROOT / ".github" / "workflows" / "import-trading-calendar.yml"
DELISTING_WORKFLOW = ROOT / ".github" / "workflows" / "import-delisting-registry.yml"


def test_calendar_schedule_runs_after_delisting_with_safe_full_range_default() -> None:
    calendar = CALENDAR_WORKFLOW.read_text(encoding="utf-8")
    delisting = DELISTING_WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "15 2 * * 0"' in delisting
    assert 'cron: "45 2 * * 0"' in calendar
    assert 'args=(--start-date "${REQUESTED_START_DATE:-2018-01-01}")' in calendar
    assert 'if [[ -n "$REQUESTED_END_DATE" ]]' in calendar
    assert 'if [[ "$DRY_RUN" == "true" ]]' in calendar
    assert "cancel-in-progress: false" in calendar
    assert 'python -m scripts.import_trading_calendar "${args[@]}"' in calendar
