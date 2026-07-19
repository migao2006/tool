"""Build a read-back verified TWSE horizon=5 research dataset."""

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
from src.data.research.twse_feature_artifact_contracts import (  # noqa: E402
    TwseFeatureArtifactManifest,
)
from src.data.research.twse_feature_artifact_reader import (  # noqa: E402
    TwseFeatureArtifactReader,
)
from src.pipeline.twse_prepared_research_artifact import (  # noqa: E402
    PreparedResearchArtifactWriter,
)
from src.pipeline.twse_research_dataset_build import (  # noqa: E402
    DAILY_BAR_FILTERS,
    TAIEX_OHLC_FILTERS,
    TwseResearchDatasetBuildError,
    TwseResearchDatasetBuilder,
)
from src.trading.cost_contracts import TransactionCostConfig  # noqa: E402
from src.trading.transaction_cost import TransactionCostModel  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify R2 daily bars, feature provenance, and official TAIEX OHLC "
            "before writing a horizon=5 RESEARCH_ONLY prepared dataset."
        )
    )
    _ = parser.add_argument("--feature", required=True, type=Path)
    _ = parser.add_argument("--feature-manifest", required=True, type=Path)
    _ = parser.add_argument("--output", required=True, type=Path)
    _ = parser.add_argument("--audit", required=True, type=Path)
    _ = parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    _ = parser.add_argument("--horizon", type=int, default=5)
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


def _feature_manifest(path: Path) -> TwseFeatureArtifactManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TwseResearchDatasetBuildError(
            "TWSE_FEATURE_ARTIFACT_MANIFEST_READ_FAILED",
            "Unable to read the persisted feature artifact manifest",
        ) from error
    if not isinstance(payload, Mapping):
        raise TwseResearchDatasetBuildError(
            "TWSE_FEATURE_ARTIFACT_MANIFEST_INVALID",
            "Feature artifact manifest JSON must be an object",
        )
    values = payload.get("feature_artifact_manifest", payload)
    if not isinstance(values, Mapping):
        raise TwseResearchDatasetBuildError(
            "TWSE_FEATURE_ARTIFACT_MANIFEST_INVALID",
            "Feature artifact sidecar does not contain a manifest object",
        )
    return TwseFeatureArtifactManifest.from_mapping(
        cast(Mapping[str, object], values)
    )


def _failure_payload(error: Exception, horizon: int) -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_status": "FAIL",
        "system_status": "FAIL",
        "usage_scope": "MODEL_RESEARCH_ONLY",
        "horizon": horizon,
        "reason_codes": [
            getattr(error, "reason_code", "TWSE_RESEARCH_DATASET_BUILD_FAILED")
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    horizon = cast(int, arguments.horizon)
    output = cast(Path, arguments.output)
    audit = cast(Path, arguments.audit)
    candidate = output.with_name(f".{output.name}.{uuid4().hex}.candidate")
    try:
        if horizon != 5:
            raise TwseResearchDatasetBuildError(
                "UNSUPPORTED_HORIZON",
                "Only horizon=5 has an independent prepared-dataset contract",
            )
        config = load_mvp_config(cast(Path, arguments.config))
        source = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        manifests = HistoricalArchiveManifestRepository(source)
        daily_snapshot = manifests.fetch(filters=DAILY_BAR_FILTERS)
        benchmark_snapshot = manifests.fetch(filters=TAIEX_OHLC_FILTERS)
        feature_reader = TwseFeatureArtifactReader()
        feature_artifact = feature_reader.verify(
            cast(Path, arguments.feature),
            _feature_manifest(cast(Path, arguments.feature_manifest)),
        )
        result = TwseResearchDatasetBuilder(
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
        artifact_manifest = PreparedResearchArtifactWriter().write(candidate, result)
        output.parent.mkdir(parents=True, exist_ok=True)
        _ = candidate.replace(output)
        payload = result.audit_payload()
        payload["build_status"] = "COMPLETED_RESEARCH_ONLY"
        payload["output_file"] = output.name
        payload["prepared_artifact_manifest"] = artifact_manifest.to_dict()
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
