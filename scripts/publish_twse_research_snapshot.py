"""Train the TWSE price-only baseline and emit a local OOS research snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import sys
from typing import cast
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.config.loader import DEFAULT_CONFIG_PATH  # noqa: E402
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.research.twse_research_prediction_supabase import (  # noqa: E402
    TwseResearchPredictionSupabasePublisher,
)
from src.pipeline.contracts import PipelineMode, PipelineStatus  # noqa: E402
from src.pipeline.orchestrator import PipelineOrchestrator  # noqa: E402
from src.pipeline.twse_prepared_research_repository import (  # noqa: E402
    PreparedResearchArtifactRepository,
)
from src.pipeline.twse_research_runner import (  # noqa: E402
    twse_price_research_runner,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run purged walk-forward research on one verified prepared Parquet "
            "dataset and write the latest OOS cross-section as versioned JSON."
        )
    )
    _ = parser.add_argument("--input", required=True, type=Path)
    _ = parser.add_argument("--input-audit", required=True, type=Path)
    _ = parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    _ = parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    _ = parser.add_argument("--report", type=Path)
    _ = parser.add_argument("--horizon", type=int, default=5)
    _ = parser.add_argument(
        "--publish-supabase",
        action="store_true",
        help=(
            "Publish a conservative RESEARCH_ONLY snapshot; requires the explicit "
            "RESEARCH_PREDICTION_SUPABASE_PUBLISH_ENABLED feature gate. Production "
            "also requires RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED."
        ),
    )
    return parser


def _write_report(path: Path | None, payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    horizon = cast(int, arguments.horizon)
    if horizon != 5:
        _write_report(
            cast(Path | None, arguments.report),
            {
                "mode": "train",
                "horizon": horizon,
                "status": "FAIL",
                "reason_codes": ["UNSUPPORTED_HORIZON"],
                "artifacts": {},
            },
        )
        return 1
    result = PipelineOrchestrator(
        config_path=cast(Path, arguments.config),
        artifact_root=cast(Path, arguments.artifact_root),
    ).run(
        mode=PipelineMode.TRAIN,
        horizon=horizon,
        repository=PreparedResearchArtifactRepository(
            cast(Path, arguments.input),
            cast(Path, arguments.input_audit),
        ),
        runner=twse_price_research_runner,
    )
    payload = cast(dict[str, object], result.to_dict())
    publish_supabase = cast(bool, arguments.publish_supabase)
    if publish_supabase and result.artifacts.get("research_prediction_snapshot"):
        try:
            uri = result.artifacts["research_prediction_snapshot"]
            parsed = urlparse(uri)
            if parsed.scheme != "file":
                raise ValueError(
                    "research prediction artifact must be a local file URI"
                )
            artifact_path = Path(url2pathname(unquote(parsed.path)))
            raw_snapshot = cast(
                object,
                json.loads(artifact_path.read_text(encoding="utf-8")),
            )
            if not isinstance(raw_snapshot, Mapping):
                raise ValueError("research prediction artifact must be a JSON object")
            published = TwseResearchPredictionSupabasePublisher(
                SupabaseWriter(
                    url=os.environ.get("SUPABASE_URL"),
                    server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
                ),
                target_environment=os.environ.get("ALPHA_LENS_TARGET_ENVIRONMENT", ""),
                publish_enabled=(
                    os.environ.get(
                        "RESEARCH_PREDICTION_SUPABASE_PUBLISH_ENABLED", ""
                    ).lower()
                    == "true"
                ),
                production_publish_enabled=(
                    os.environ.get(
                        "RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED", ""
                    ).lower()
                    == "true"
                ),
            ).publish(cast(Mapping[str, object], raw_snapshot))
            payload["supabase_publish"] = {
                "status": "COMPLETED",
                "target_environment": published.target_environment,
                "prediction_run_id": published.prediction_run_id,
                "prediction_count": published.prediction_count,
            }
        except Exception as error:
            payload["supabase_publish"] = {
                "status": "FAIL",
                "reason_codes": ["RESEARCH_SUPABASE_PUBLISH_FAILED"],
                "message": str(error),
            }
            _write_report(cast(Path | None, arguments.report), payload)
            return 1
    _write_report(cast(Path | None, arguments.report), payload)
    has_snapshot = bool(result.artifacts.get("research_prediction_snapshot"))
    if result.status is PipelineStatus.RESEARCH_ONLY and has_snapshot:
        return 0
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
