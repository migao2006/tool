"""Train a TPEX bundle and publish one latest research snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
from typing import cast
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.config.loader import DEFAULT_CONFIG_PATH, load_mvp_config  # noqa: E402
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.research.twse_research_prediction_supabase import (  # noqa: E402
    TpexResearchPredictionSupabasePublisher,
)
from src.pipeline.contracts import PipelineMode, PipelineStatus  # noqa: E402
from src.pipeline.orchestrator import PipelineOrchestrator  # noqa: E402
from src.pipeline.tpex_latest_feature_repository import (  # noqa: E402
    LatestTpexDailyFeatureRepository,
)
from src.pipeline.tpex_research_daily_inference import (  # noqa: E402
    TpexDailyResearchInference,
)
from src.pipeline.tpex_research_runner import tpex_price_research_runner  # noqa: E402
from src.pipeline.twse_prepared_research_repository import (  # noqa: E402
    PreparedResearchArtifactRepository,
)
from src.pipeline.twse_research_model_bundle_io import (  # noqa: E402
    TwseResearchBundleReader,
)
from src.pipeline.twse_research_snapshot_writer import (  # noqa: E402
    persist_research_snapshot,
)


class TpexDailyResearchPublishError(RuntimeError):
    """Stable fail-closed reason exposed by the CLI report."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


_RUN_ID = re.compile(r"^[1-9][0-9]*$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _inference_feature_source() -> dict[str, object] | None:
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() != "true":
        return None
    values = {
        "run_id": os.environ.get("TPEX_INFERENCE_FEATURE_SOURCE_RUN_ID", "").strip(),
        "run_sha": os.environ.get("TPEX_INFERENCE_FEATURE_SOURCE_RUN_SHA", "")
        .strip()
        .lower(),
        "artifact_id": os.environ.get(
            "TPEX_INFERENCE_FEATURE_SOURCE_ARTIFACT_ID", ""
        ).strip(),
        "artifact_digest": os.environ.get(
            "TPEX_INFERENCE_FEATURE_SOURCE_ARTIFACT_DIGEST", ""
        )
        .strip()
        .lower(),
    }
    if (
        _RUN_ID.fullmatch(values["run_id"]) is None
        or _GIT_SHA.fullmatch(values["run_sha"]) is None
        or _RUN_ID.fullmatch(values["artifact_id"]) is None
        or _ARTIFACT_DIGEST.fullmatch(values["artifact_digest"]) is None
    ):
        raise TpexDailyResearchPublishError(
            "TPEX_INFERENCE_FEATURE_SOURCE_PROVENANCE_INVALID",
            "TPEX inference feature workflow provenance is incomplete",
        )
    return {
        "artifact_kind": "TPEX_DAILY_FEATURE_DELTA",
        "producer_workflow": (".github/workflows/build-tpex-daily-feature-delta.yml"),
        **values,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fit the mechanically last validated TPEX fold and score the latest "
            "verified feature-only cross-section as RESEARCH_ONLY."
        )
    )
    _ = parser.add_argument("--prepared-input", required=True, type=Path)
    _ = parser.add_argument("--prepared-audit", required=True, type=Path)
    _ = parser.add_argument("--feature-input", required=True, type=Path)
    _ = parser.add_argument("--feature-audit", required=True, type=Path)
    _ = parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    _ = parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    _ = parser.add_argument("--report", type=Path)
    _ = parser.add_argument("--horizon", type=int, default=5)
    _ = parser.add_argument("--required-as-of-date", type=date.fromisoformat)
    _ = parser.add_argument("--publish-supabase", action="store_true")
    return parser


def _local_path(uri: str, *, directory: bool = False) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError("research artifacts must use local file URIs")
    path = Path(url2pathname(unquote(parsed.path)))
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        raise ValueError("research artifact path is unavailable")
    return path


def _write_report(path: Path | None, payload: Mapping[str, object]) -> None:
    rendered = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _publish(payload: Mapping[str, object]) -> dict[str, object]:
    result = TpexResearchPredictionSupabasePublisher(
        SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        ),
        target_environment=os.environ.get("ALPHA_LENS_TARGET_ENVIRONMENT", ""),
        publish_enabled=(
            os.environ.get("RESEARCH_PREDICTION_SUPABASE_PUBLISH_ENABLED", "").lower()
            == "true"
        ),
        production_publish_enabled=(
            os.environ.get("RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED", "").lower()
            == "true"
        ),
    ).publish(payload)
    return {
        "status": "COMPLETED",
        "market": "TPEX",
        "target_environment": result.target_environment,
        "prediction_run_id": result.prediction_run_id,
        "prediction_count": result.prediction_count,
        "decision_gate_count": result.decision_gate_count,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    report_path = cast(Path | None, arguments.report)
    horizon = cast(int, arguments.horizon)
    if horizon != 5:
        _write_report(
            report_path,
            {
                "status": "FAIL",
                "market": "TPEX",
                "horizon": horizon,
                "reason_codes": ["UNSUPPORTED_HORIZON"],
            },
        )
        return 1
    try:
        artifact_root = cast(Path, arguments.artifact_root)
        config_path = cast(Path, arguments.config)
        training = PipelineOrchestrator(
            config_path=config_path,
            artifact_root=artifact_root,
        ).run(
            mode=PipelineMode.TRAIN,
            horizon=5,
            repository=PreparedResearchArtifactRepository(
                cast(Path, arguments.prepared_input),
                cast(Path, arguments.prepared_audit),
                expected_market="TPEX",
            ),
            runner=tpex_price_research_runner,
        )
        bundle_uri = training.artifacts.get("research_model_bundle")
        if training.status is not PipelineStatus.RESEARCH_ONLY or not bundle_uri:
            reason_code = next(
                iter(training.reason_codes),
                "TPEX_RESEARCH_MODEL_BUNDLE_NOT_CREATED",
            )
            raise TpexDailyResearchPublishError(
                reason_code,
                "TPEX research training did not produce a verified bundle",
            )
        bundle_dir = _local_path(bundle_uri, directory=True)
        bundle = TwseResearchBundleReader.read(bundle_dir, expected_market="TPEX")
        features = LatestTpexDailyFeatureRepository().load(
            cast(Path, arguments.feature_input),
            cast(Path, arguments.feature_audit),
            as_of_date=cast(date | None, arguments.required_as_of_date),
        )
        required_as_of_date = cast(date | None, arguments.required_as_of_date)
        if (
            required_as_of_date is not None
            and features.as_of_date != required_as_of_date
        ):
            raise ValueError("TPEX_REQUIRED_AS_OF_DATE_NOT_AVAILABLE")
        snapshot = TpexDailyResearchInference().run(
            features,
            bundle,
            load_mvp_config(config_path),
            feature_source_provenance=_inference_feature_source(),
        )
        output = (
            artifact_root
            / "horizon_5"
            / "research"
            / (
                f"tpex-{snapshot.predictions[0].evaluation_scope.lower()}-"
                f"{snapshot.as_of_date.isoformat()}-{snapshot.snapshot_sha256[:12]}.json"
            )
        )
        persisted = persist_research_snapshot(output, snapshot)
        payload = snapshot.to_dict()
        report: dict[str, object] = {
            "status": "RESEARCH_ONLY",
            "market": "TPEX",
            "horizon": 5,
            "as_of_date": snapshot.as_of_date.isoformat(),
            "evaluation_scope": snapshot.predictions[0].evaluation_scope,
            "prediction_count": len(snapshot.predictions),
            "model_version": snapshot.model_version,
            "model_bundle_sha256": bundle.manifest.manifest_sha256,
            "feature_artifact_sha256": features.manifest.parquet_sha256,
            "snapshot_sha256": snapshot.snapshot_sha256,
            "artifact_sha256": persisted.artifact_sha256,
            "artifacts": {
                "research_model_bundle": bundle_dir.resolve().as_uri(),
                "daily_research_snapshot": output.resolve().as_uri(),
            },
            "reason_codes": list(snapshot.reason_codes),
        }
        if cast(bool, arguments.publish_supabase):
            report["supabase_publish"] = _publish(payload)
        _write_report(report_path, report)
        return 0
    except Exception as error:  # fail closed at the CLI boundary
        _write_report(
            report_path,
            {
                "status": "FAIL",
                "market": "TPEX",
                "horizon": 5,
                "reason_codes": [
                    str(
                        getattr(
                            error,
                            "reason_code",
                            "TPEX_DAILY_RESEARCH_INFERENCE_FAILED",
                        )
                    )
                ],
                "message": str(error),
            },
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
