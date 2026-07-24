"""Publish one previously verified research snapshot to the selected Supabase target."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from typing import cast

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.pipeline.daily_research_publish_contract import (  # noqa: E402
    MIN_DAILY_RESEARCH_PREDICTIONS,
)
from src.data.research.twse_research_prediction_supabase_contracts import (  # noqa: E402
    ResearchSupabasePublishResult,
)
from src.data.research.twse_research_prediction_supabase import (  # noqa: E402
    TpexResearchPredictionSupabasePublisher,
    TwseResearchPredictionSupabasePublisher,
)


_RESEARCH_PUBLISH_TIMEOUT_SECONDS = 60.0
_RESEARCH_PUBLISH_RETRY_DELAYS_SECONDS = (1.0, 2.0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish an immutable exact-date research snapshot without retraining."
    )
    _ = parser.add_argument("--market", choices=("TWSE", "TPEX"), required=True)
    _ = parser.add_argument("--snapshot", type=Path, required=True)
    _ = parser.add_argument("--required-as-of-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--report", type=Path, required=True)
    return parser


def _write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    _ = path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _load_snapshot(path: Path, *, market: str, as_of_date: date) -> dict[str, object]:
    try:
        raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("RESEARCH_SNAPSHOT_ARTIFACT_INVALID") from error
    if not isinstance(raw, Mapping):
        raise ValueError("RESEARCH_SNAPSHOT_ARTIFACT_INVALID")
    payload = dict(cast(Mapping[str, object], raw))
    stored_hash = str(payload.get("snapshot_sha256") or "").strip().lower()
    content = {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    computed_hash = sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if stored_hash != computed_hash:
        raise ValueError("RESEARCH_SNAPSHOT_HASH_MISMATCH")
    if payload.get("system_status") != "RESEARCH_ONLY" or payload.get("horizon") != 5:
        raise ValueError("RESEARCH_SNAPSHOT_CONTRACT_INVALID")
    if str(payload.get("as_of_date") or "") != as_of_date.isoformat():
        raise ValueError("RESEARCH_SNAPSHOT_REQUIRED_DATE_MISMATCH")
    snapshot_market = str(payload.get("market") or "TWSE").strip().upper()
    if snapshot_market != market:
        raise ValueError("RESEARCH_SNAPSHOT_MARKET_MISMATCH")
    predictions = payload.get("predictions")
    if (
        not isinstance(predictions, list)
        or len(predictions) < MIN_DAILY_RESEARCH_PREDICTIONS[market]
    ):
        raise ValueError("RESEARCH_SNAPSHOT_COVERAGE_TOO_LOW")
    for value in predictions:
        if not isinstance(value, Mapping):
            raise ValueError("RESEARCH_SNAPSHOT_PREDICTION_INVALID")
        prediction = cast(Mapping[str, object], value)
        if (
            str(prediction.get("market") or "").strip().upper() != market
            or str(prediction.get("decision_date") or "") != as_of_date.isoformat()
            or int(cast(int, prediction.get("horizon") or 0)) != 5
        ):
            raise ValueError("RESEARCH_SNAPSHOT_PREDICTION_SCOPE_MISMATCH")
    return payload


def _publisher(market: str, writer: SupabaseWriter):
    options = {
        "target_environment": os.environ.get("ALPHA_LENS_TARGET_ENVIRONMENT", ""),
        "publish_enabled": os.environ.get(
            "RESEARCH_PREDICTION_SUPABASE_PUBLISH_ENABLED", ""
        ).lower()
        == "true",
        "production_publish_enabled": os.environ.get(
            "RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED", ""
        ).lower()
        == "true",
    }
    return (
        TwseResearchPredictionSupabasePublisher(writer, **options)
        if market == "TWSE"
        else TpexResearchPredictionSupabasePublisher(writer, **options)
    )


def _research_writer() -> SupabaseWriter:
    return SupabaseWriter(
        url=os.environ.get("SUPABASE_URL"),
        server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        timeout=_RESEARCH_PUBLISH_TIMEOUT_SECONDS,
    )


def _publish_with_connection_retry(
    publish_once: Callable[[], ResearchSupabasePublishResult],
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> ResearchSupabasePublishResult:
    """Replay only this immutable publisher after an ambiguous connection loss."""

    for attempt in range(len(_RESEARCH_PUBLISH_RETRY_DELAYS_SECONDS) + 1):
        try:
            return publish_once()
        except IngestionError as error:
            if (
                error.reason_code != "SUPABASE_CONNECTION_ERROR"
                or attempt == len(_RESEARCH_PUBLISH_RETRY_DELAYS_SECONDS)
            ):
                raise
            delay = _RESEARCH_PUBLISH_RETRY_DELAYS_SECONDS[attempt]
            print(
                "Retrying immutable research publish after "
                f"{error.reason_code} (attempt {attempt + 2}/3)",
                file=sys.stderr,
            )
            sleeper(delay)
    raise AssertionError("unreachable research publish retry state")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    market = cast(str, arguments.market)
    snapshot_path = cast(Path, arguments.snapshot)
    required_date = cast(date, arguments.required_as_of_date)
    report_path = cast(Path, arguments.report)
    try:
        payload = _load_snapshot(
            snapshot_path,
            market=market,
            as_of_date=required_date,
        )
        result = _publish_with_connection_retry(
            lambda: _publisher(market, _research_writer()).publish(payload)
        )
        report: dict[str, object] = {
            "status": "RESEARCH_ONLY",
            "market": market,
            "as_of_date": required_date.isoformat(),
            "snapshot_sha256": payload["snapshot_sha256"],
            "prediction_count": len(cast(list[object], payload["predictions"])),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "supabase_publish": {
                "status": "COMPLETED",
                "target_environment": result.target_environment,
                "prediction_run_id": result.prediction_run_id,
                "prediction_count": result.prediction_count,
                "decision_gate_count": result.decision_gate_count,
                "market_prediction_count": result.market_prediction_count,
            },
        }
        _write(report_path, report)
        return 0
    except Exception as error:
        _write(
            report_path,
            {
                "status": "FAIL",
                "market": market,
                "as_of_date": required_date.isoformat(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "reason_codes": [
                    str(
                        getattr(
                            error,
                            "reason_code",
                            "STORED_RESEARCH_SNAPSHOT_PUBLISH_FAILED",
                        )
                    )
                ],
                "message": str(error),
            },
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
