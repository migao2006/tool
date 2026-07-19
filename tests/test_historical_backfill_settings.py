from pathlib import Path

import pytest

from src.data.ingestion.historical_backfill_settings import HistoricalBackfillSettings


ROOT = Path(__file__).resolve().parents[1]


def test_settings_default_to_supabase_storage_without_r2_environment() -> None:
    settings = HistoricalBackfillSettings.from_env({})

    assert settings.storage_target == "SUPABASE"
    assert settings.max_archive_objects_per_run == 100
    assert settings.max_archive_object_bytes == 50_000_000
    assert settings.seed_common_tasks is True
    assert settings.seed_delisted_tasks is False
    assert settings.refresh_home_status is True


def test_env_example_lists_runtime_names_without_values() -> None:
    declarations = {
        name: value
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
        for name, value in [line.split("=", maxsplit=1)]
    }

    assert {
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "HISTORICAL_BACKFILL_STORAGE_TARGET",
        "HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECTS_PER_RUN",
        "HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES",
        "HISTORICAL_BACKFILL_SEED_COMMON_TASKS",
        "HISTORICAL_BACKFILL_REFRESH_HOME_STATUS",
    } <= declarations.keys()
    assert set(declarations.values()) == {""}


def test_settings_parse_and_normalize_r2_archive_limits() -> None:
    settings = HistoricalBackfillSettings.from_env(
        {
            "HISTORICAL_BACKFILL_STORAGE_TARGET": " r2 ",
            "HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECTS_PER_RUN": "24",
            "HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES": "12500000",
        }
    )

    assert settings.storage_target == "R2"
    assert settings.max_archive_objects_per_run == 24
    assert settings.max_archive_object_bytes == 12_500_000


def test_settings_can_disable_worker_home_status_refresh() -> None:
    settings = HistoricalBackfillSettings.from_env(
        {"HISTORICAL_BACKFILL_REFRESH_HOME_STATUS": " false "}
    )

    assert settings.refresh_home_status is False


def test_settings_can_disable_shared_common_task_seeding() -> None:
    settings = HistoricalBackfillSettings.from_env(
        {"HISTORICAL_BACKFILL_SEED_COMMON_TASKS": " false "}
    )

    assert settings.seed_common_tasks is False


def test_settings_can_enable_delisted_task_seeding() -> None:
    settings = HistoricalBackfillSettings.from_env(
        {"HISTORICAL_BACKFILL_SEED_DELISTED_TASKS": " true "}
    )

    assert settings.seed_delisted_tasks is True


@pytest.mark.parametrize("value", ["enabled", "2", "sometimes"])
def test_settings_reject_invalid_common_task_seed_flag(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="HISTORICAL_BACKFILL_SEED_COMMON_TASKS must be true or false",
    ):
        _ = HistoricalBackfillSettings.from_env(
            {"HISTORICAL_BACKFILL_SEED_COMMON_TASKS": value}
        )


@pytest.mark.parametrize("value", ["enabled", "2", "sometimes"])
def test_settings_reject_invalid_delisted_task_seed_flag(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="HISTORICAL_BACKFILL_SEED_DELISTED_TASKS must be true or false",
    ):
        _ = HistoricalBackfillSettings.from_env(
            {"HISTORICAL_BACKFILL_SEED_DELISTED_TASKS": value}
        )


@pytest.mark.parametrize("value", ["enabled", "2", "sometimes"])
def test_settings_reject_invalid_home_status_refresh_flag(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="HISTORICAL_BACKFILL_REFRESH_HOME_STATUS must be true or false",
    ):
        _ = HistoricalBackfillSettings.from_env(
            {"HISTORICAL_BACKFILL_REFRESH_HOME_STATUS": value}
        )


@pytest.mark.parametrize("value", ["", "postgres", "r2-public"])
def test_settings_reject_unknown_storage_targets(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="HISTORICAL_BACKFILL_STORAGE_TARGET must be SUPABASE or R2",
    ):
        _ = HistoricalBackfillSettings.from_env(
            {"HISTORICAL_BACKFILL_STORAGE_TARGET": value}
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECTS_PER_RUN", "0"),
        ("HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECTS_PER_RUN", "101"),
        ("HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES", "999999"),
        ("HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES", "500000001"),
        ("HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES", "not-an-integer"),
    ],
)
def test_settings_reject_invalid_archive_limits(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        _ = HistoricalBackfillSettings.from_env({name: value})
