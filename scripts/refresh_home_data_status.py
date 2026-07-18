"""Refresh the public data-status aggregate once after parallel import workers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import os
from time import sleep
import sys
from typing import Protocol

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402


_RETRYABLE_CODES = {"SUPABASE_CONNECTION_ERROR", "SUPABASE_WRITE_REJECTED"}


class HomeStatusWriter(Protocol):
    """Small contract used by the finalizer and its retry tests."""

    def refresh_home_data_status(self) -> None: ...


def refresh_with_retry(
    writer: HomeStatusWriter,
    *,
    attempts: int = 3,
    sleep_fn: Callable[[float], None] = sleep,
) -> None:
    """Retry the idempotent aggregate refresh after transient API timeouts."""

    if attempts <= 0:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        try:
            writer.refresh_home_data_status()
            return
        except IngestionError as error:
            if error.reason_code not in _RETRYABLE_CODES or attempt + 1 >= attempts:
                raise
            sleep_fn(2.0**attempt)


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason_code": "UNEXPECTED_ARGUMENT",
                    "message": "This command does not accept arguments",
                },
                sort_keys=True,
            )
        )
        return 2
    try:
        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            timeout=30.0,
        )
        refresh_with_retry(writer)
    except (IngestionError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason_code": getattr(
                        error, "reason_code", "HOME_STATUS_REFRESH_CONFIGURATION_ERROR"
                    ),
                    "message": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {"status": "PASS", "outcome": "HOME_DATA_STATUS_REFRESHED"},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
