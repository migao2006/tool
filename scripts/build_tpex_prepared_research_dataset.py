"""Build a read-back verified TPEX horizon=5 research dataset."""

from __future__ import annotations

# pyright: reportAny=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import cast
from uuid import uuid4

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.config.loader import DEFAULT_CONFIG_PATH, load_mvp_config  # noqa: E402
from src.data.archive.historical_parquet_reader import HistoricalParquetReader  # noqa: E402
from src.data.archive.manifest_repository import (  # noqa: E402
    HistoricalArchiveManifestRepository,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.data.research.tpex_feature_artifact_contracts import (  # noqa: E402
    TpexFeatureArtifactManifest,
)
from src.data.research.tpex_feature_artifact_reader import (  # noqa: E402
    TpexFeatureArtifactReader,
)
from src.pipeline.tpex_research_dataset_build import (  # noqa: E402
    TPEX_DAILY_BAR_FILTERS,
    TPEX_OHLC_FILTERS,
    TpexResearchDatasetBuildError,
    TpexResearchDatasetBuilder,
)
from src.pipeline.twse_prepared_research_artifact import (  # noqa: E402
    PreparedResearchArtifactWriter,
)
from src.pipeline.twse_prepared_research_contracts import (  # noqa: E402
    FeatureArtifactSourceProvenance,
)
from src.trading.cost_contracts import TransactionCostConfig  # noqa: E402
from src.trading.transaction_cost import TransactionCostModel  # noqa: E402


MAX_DAILY_MANIFESTS = 5_000
MAX_BENCHMARK_MANIFESTS = 240


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify TPEX daily bars, feature provenance, and official TPEX "
            "price-index OHLC before writing a horizon=5 RESEARCH_ONLY dataset."
        )
    )
    _ = parser.add_argument("--feature", required=True, type=Path)
    _ = parser.add_argument("--feature-manifest", required=True, type=Path)
    _ = parser.add_argument("--output", required=True, type=Path)
    _ = parser.add_argument("--audit", required=True, type=Path)
    _ = parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    _ = parser.add_argument("--horizon", type=int, default=5)
    _ = parser.add_argument("--feature-source-run-id")
    _ = parser.add_argument("--feature-source-run-sha")
    _ = parser.add_argument("--feature-source-artifact-id")
    _ = parser.add_argument("--feature-source-artifact-digest")
    _ = parser.add_argument(
        "--cost-profile",
        choices=("low_cost", "base_cost", "stressed_cost", "extreme_cost"),
        default="base_cost",
    )
    return parser


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.partial")
    _ = temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = temporary.replace(path)


def _feature_manifest(path: Path) -> TpexFeatureArtifactManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TpexResearchDatasetBuildError(
            "TPEX_FEATURE_ARTIFACT_MANIFEST_READ_FAILED",
            "Unable to read the persisted TPEX feature manifest",
        ) from error
    if not isinstance(payload, Mapping):
        raise TpexResearchDatasetBuildError(
            "TPEX_FEATURE_ARTIFACT_MANIFEST_INVALID",
            "TPEX feature artifact sidecar must be an object",
        )
    values = payload.get("feature_artifact_manifest", payload)
    if not isinstance(values, Mapping):
        raise TpexResearchDatasetBuildError(
            "TPEX_FEATURE_ARTIFACT_MANIFEST_INVALID",
            "TPEX feature artifact sidecar has no manifest object",
        )
    return TpexFeatureArtifactManifest.from_mapping(cast(Mapping[str, object], values))


def _failure_payload(error: Exception, horizon: int) -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_status": "FAIL",
        "system_status": "FAIL",
        "usage_scope": "MODEL_RESEARCH_ONLY",
        "market": "TPEX",
        "horizon": horizon,
        "reason_codes": [
            getattr(error, "reason_code", "TPEX_RESEARCH_DATASET_BUILD_FAILED")
        ],
    }


def _feature_source(arguments: argparse.Namespace) -> FeatureArtifactSourceProvenance:
    run_id = str(arguments.feature_source_run_id or "").strip()
    run_sha = str(arguments.feature_source_run_sha or "").strip().lower()
    artifact_id = str(arguments.feature_source_artifact_id or "").strip()
    raw_digest = str(arguments.feature_source_artifact_digest or "").strip().lower()
    if not run_id or not run_sha or not artifact_id or not raw_digest:
        raise TpexResearchDatasetBuildError(
            "TPEX_FEATURE_SOURCE_PROVENANCE_MISSING",
            "A trusted TPEX feature workflow source is required",
        )
    try:
        return FeatureArtifactSourceProvenance(
            run_id=run_id,
            run_sha=run_sha,
            artifact_id=artifact_id,
            artifact_digest=raw_digest or None,
        )
    except ValueError as error:
        raise TpexResearchDatasetBuildError(
            "TPEX_FEATURE_SOURCE_PROVENANCE_INVALID",
            "A trusted TPEX feature workflow source is required",
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    horizon = cast(int, arguments.horizon)
    output = cast(Path, arguments.output)
    audit = cast(Path, arguments.audit)
    candidate = output.with_name(f".{output.name}.{uuid4().hex}.candidate")
    try:
        if horizon != 5:
            raise TpexResearchDatasetBuildError(
                "UNSUPPORTED_HORIZON",
                "Only horizon=5 has a TPEX prepared-dataset contract",
            )
        feature_source = _feature_source(arguments)
        config = load_mvp_config(cast(Path, arguments.config))
        source = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        manifests = HistoricalArchiveManifestRepository(source)
        daily_snapshot = manifests.fetch(
            filters=TPEX_DAILY_BAR_FILTERS,
            max_objects=MAX_DAILY_MANIFESTS,
        )
        benchmark_snapshot = manifests.fetch(
            filters=TPEX_OHLC_FILTERS,
            max_objects=MAX_BENCHMARK_MANIFESTS,
        )
        feature_reader = TpexFeatureArtifactReader()
        feature_artifact = feature_reader.verify(
            cast(Path, arguments.feature),
            _feature_manifest(cast(Path, arguments.feature_manifest)),
        )
        result = TpexResearchDatasetBuilder(
            HistoricalParquetReader(R2Client.from_env()),
            feature_reader=feature_reader,
        ).build(
            daily_manifests=daily_snapshot,
            benchmark_manifests=benchmark_snapshot,
            feature_artifact=feature_artifact,
            horizon=horizon,
            transaction_cost_model=TransactionCostModel(
                TransactionCostConfig.from_settings(config.cost)
            ),
            cost_profile=cast(str, arguments.cost_profile),
        )
        artifact_manifest = PreparedResearchArtifactWriter().write(
            candidate,
            result,
            feature_source=feature_source,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        _ = candidate.replace(output)
        payload = result.audit_payload()
        payload["build_status"] = "COMPLETED_RESEARCH_ONLY"
        payload["output_file"] = output.name
        payload["prepared_artifact_manifest"] = artifact_manifest.to_dict()
        payload["feature_source_provenance"] = feature_source.to_dict()
        payload["prepared_artifact_read_back_verified"] = True
        _write_json(audit, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as error:  # fail closed at the external I/O boundary
        candidate.unlink(missing_ok=True)
        payload = _failure_payload(error, horizon)
        _write_json(audit, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
