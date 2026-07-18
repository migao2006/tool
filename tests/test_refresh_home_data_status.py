import pytest
from typing import final

from scripts.refresh_home_data_status import main, refresh_with_retry
from src.data.ingestion.contracts import IngestionError


@final
class FakeHomeStatusWriter:
    def __init__(self, failures: list[IngestionError] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls = 0

    def refresh_home_data_status(self) -> None:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)


def transient_error() -> IngestionError:
    return IngestionError("SUPABASE_WRITE_REJECTED", "temporary timeout")


def test_refresh_retries_transient_failures_with_bounded_backoff() -> None:
    writer = FakeHomeStatusWriter([transient_error(), transient_error()])
    sleeps: list[float] = []

    refresh_with_retry(writer, attempts=3, sleep_fn=sleeps.append)

    assert writer.calls == 3
    assert sleeps == [1.0, 2.0]


def test_refresh_does_not_retry_non_transient_failures() -> None:
    writer = FakeHomeStatusWriter(
        [IngestionError("SUPABASE_CONFIGURATION_MISSING", "missing configuration")]
    )

    def fail_if_called(_seconds: float) -> None:
        pytest.fail("non-transient errors must not be retried")

    with pytest.raises(IngestionError, match="missing configuration"):
        refresh_with_retry(writer, attempts=3, sleep_fn=fail_if_called)

    assert writer.calls == 1


def test_refresh_requires_a_positive_attempt_limit() -> None:
    with pytest.raises(ValueError, match="attempts must be positive"):
        refresh_with_retry(FakeHomeStatusWriter(), attempts=0)


def test_refresh_command_rejects_arguments_without_connecting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["unexpected"]) == 2
    output = capsys.readouterr().out
    assert '"reason_code": "UNEXPECTED_ARGUMENT"' in output
