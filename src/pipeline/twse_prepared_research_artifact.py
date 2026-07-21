"""Write and read-back verify one venue-scoped prepared research artifact."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, cast, final

from .research_dataset import PreparedResearchDataset
from .twse_prepared_research_contracts import (
    PREPARED_ARTIFACT_VERSION,
    FeatureArtifactSourceProvenance,
    PreparedResearchArtifactError,
    PreparedResearchArtifactManifest,
    artifact_version_for_market,
)
from .twse_research_dataset_build import ResearchDatasetBuildResult


def _modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise PreparedResearchArtifactError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to persist the research dataset",
        ) from error
    return pa, pq


def _schema_digest(schema: Any) -> str:
    fields = [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema.remove_metadata()
    ]
    encoded = json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


def _metadata(
    result: ResearchDatasetBuildResult,
    feature_source: FeatureArtifactSourceProvenance | None,
) -> dict[bytes, bytes]:
    audit = result.assembly.audit
    metadata = {
        b"artifact.version": artifact_version_for_market(audit.market).encode(),
        b"system.status": b"RESEARCH_ONLY",
        b"usage.scope": b"MODEL_RESEARCH_ONLY",
        b"market": audit.market.encode(),
        b"horizon": b"5",
        b"benchmark.path": b"T_PLUS_ONE_OPEN_TO_H_CLOSE",
        b"benchmark.semantics": b"PRICE_INDEX_NOT_TOTAL_RETURN",
        b"prepared_dataset.snapshot_sha256": (
            result.prepared_dataset_snapshot_sha256.encode()
        ),
        b"daily_archive.snapshot_sha256": (
            result.daily_archive_snapshot_sha256.encode()
        ),
        b"current_identity.snapshot_sha256": (
            result.current_identity_snapshot_sha256.encode()
        ),
        b"feature_artifact.sha256": result.feature_artifact_sha256.encode(),
        b"calendar.snapshot_sha256": result.calendar_snapshot_sha256.encode(),
        b"benchmark.snapshot_sha256": result.benchmark_snapshot_sha256.encode(),
        b"benchmark.id": audit.benchmark_id.encode(),
        b"benchmark.version": result.benchmark_version.encode(),
        b"dataset.snapshot_id": audit.dataset_snapshot_id.encode(),
        b"source.hash": audit.source_hash.encode(),
        b"feature.schema_hash": audit.feature_schema_hash.encode(),
        b"label.version": audit.label_version.encode(),
        b"cost.profile_version": audit.cost_profile_version.encode(),
        b"reason_codes.encoding": b"canonical-json-v1",
    }
    if feature_source is not None:
        metadata.update(
            {
                b"feature.source_run_id": feature_source.run_id.encode(),
                b"feature.source_run_sha": feature_source.run_sha.encode(),
                b"feature.source_artifact_id": feature_source.artifact_id.encode(),
            }
        )
        if feature_source.artifact_digest is not None:
            metadata[b"feature.source_artifact_digest"] = (
                feature_source.artifact_digest.encode()
            )
    return metadata


def _table_for_result(
    result: ResearchDatasetBuildResult,
    feature_source: FeatureArtifactSourceProvenance | None,
) -> Any:
    pa, _ = _modules()
    audit = result.assembly.audit
    dataset = PreparedResearchDataset.from_frame(
        result.assembly.prepared_rows,
        market=audit.market,
        feature_schema_hash=audit.feature_schema_hash,
    )
    frame = dataset.frame.copy()
    frame["reason_codes"] = frame["reason_codes"].map(
        lambda value: json.dumps(
            list(value),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    table = pa.Table.from_pandas(frame, preserve_index=False)
    return table.replace_schema_metadata(_metadata(result, feature_source))


def _write(path: Path, table: Any) -> None:
    _, pq = _modules()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            table,
            path,
            compression="zstd",
            compression_level=9,
            version="2.6",
            data_page_version="2.0",
            write_statistics=True,
            coerce_timestamps="us",
            allow_truncated_timestamps=False,
        )
    except Exception as error:
        raise PreparedResearchArtifactError(
            "PREPARED_RESEARCH_ARTIFACT_WRITE_FAILED",
            "Unable to write the prepared research artifact",
        ) from error


def _digest(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                size += len(block)
    except OSError as error:
        raise PreparedResearchArtifactError(
            "PREPARED_RESEARCH_ARTIFACT_READ_FAILED",
            "Unable to read the prepared research artifact",
        ) from error
    return digest.hexdigest(), size


def _manifest(
    path: Path,
    table: Any,
    result: ResearchDatasetBuildResult,
    feature_source: FeatureArtifactSourceProvenance | None,
) -> PreparedResearchArtifactManifest:
    audit = result.assembly.audit
    digest, size = _digest(path)
    return PreparedResearchArtifactManifest(
        parquet_sha256=digest,
        schema_sha256=_schema_digest(table.schema),
        byte_size=size,
        row_count=table.num_rows,
        prepared_dataset_snapshot_sha256=(result.prepared_dataset_snapshot_sha256),
        dataset_snapshot_id=audit.dataset_snapshot_id,
        daily_archive_snapshot_sha256=result.daily_archive_snapshot_sha256,
        current_identity_snapshot_sha256=(result.current_identity_snapshot_sha256),
        feature_artifact_sha256=result.feature_artifact_sha256,
        calendar_snapshot_sha256=result.calendar_snapshot_sha256,
        source_hash=audit.source_hash,
        benchmark_snapshot_sha256=result.benchmark_snapshot_sha256,
        benchmark_id=audit.benchmark_id,
        benchmark_version=result.benchmark_version,
        feature_schema_hash=audit.feature_schema_hash,
        label_version=audit.label_version,
        cost_profile_version=audit.cost_profile_version,
        market=audit.market,
        artifact_version=artifact_version_for_market(audit.market),
        feature_source_run_id=(feature_source.run_id if feature_source else None),
        feature_source_run_sha=(feature_source.run_sha if feature_source else None),
        feature_source_artifact_id=(
            feature_source.artifact_id if feature_source else None
        ),
        feature_source_artifact_digest=(
            feature_source.artifact_digest if feature_source else None
        ),
    )


def _read_table(path: Path) -> Any:
    _, pq = _modules()
    try:
        parquet = pq.ParquetFile(path)
        compressions = {
            parquet.metadata.row_group(group).column(column).compression
            for group in range(parquet.metadata.num_row_groups)
            for column in range(parquet.metadata.num_columns)
        }
        if compressions != {"ZSTD"}:
            raise PreparedResearchArtifactError(
                "PREPARED_RESEARCH_ARTIFACT_COMPRESSION_INVALID",
                "Prepared research Parquet must use ZSTD compression",
            )
        return parquet.read()
    except PreparedResearchArtifactError:
        raise
    except Exception as error:
        raise PreparedResearchArtifactError(
            "PREPARED_RESEARCH_ARTIFACT_PARQUET_INVALID",
            "Prepared research artifact is not readable Parquet",
        ) from error


def _decoded_dataset(
    table: Any,
    expected: PreparedResearchArtifactManifest,
) -> PreparedResearchDataset:
    frame = table.to_pandas()
    try:
        frame["reason_codes"] = frame["reason_codes"].map(
            lambda value: tuple(cast(list[str], json.loads(str(value))))
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise PreparedResearchArtifactError(
            "PREPARED_RESEARCH_ARTIFACT_REASON_CODES_INVALID",
            "Prepared research reason codes are invalid",
        ) from error
    try:
        return PreparedResearchDataset.from_frame(
            frame,
            market=expected.market,
            feature_schema_hash=expected.feature_schema_hash,
        )
    except ValueError as error:
        raise PreparedResearchArtifactError(
            "PREPARED_RESEARCH_ARTIFACT_ROWS_INVALID",
            "Prepared research rows fail the frozen training contract",
        ) from error


@final
class PreparedResearchArtifactWriter:
    """Persist only validated rows and require a complete read-back."""

    def write(
        self,
        path: str | Path,
        result: ResearchDatasetBuildResult,
        *,
        feature_source: FeatureArtifactSourceProvenance | None = None,
    ) -> PreparedResearchArtifactManifest:
        output = Path(path)
        table = _table_for_result(result, feature_source)
        _write(output, table)
        manifest = _manifest(output, _read_table(output), result, feature_source)
        _ = self.verify(output, manifest)
        return manifest

    def verify(
        self,
        path: str | Path,
        expected: PreparedResearchArtifactManifest,
    ) -> PreparedResearchDataset:
        artifact_path = Path(path)
        digest, size = _digest(artifact_path)
        if digest != expected.parquet_sha256 or size != expected.byte_size:
            raise PreparedResearchArtifactError(
                "PREPARED_RESEARCH_ARTIFACT_MANIFEST_MISMATCH",
                "Prepared research bytes do not match their manifest",
            )
        table = _read_table(artifact_path)
        dataset = _decoded_dataset(table, expected)
        observed_result_metadata = cast(dict[bytes, bytes], table.schema.metadata or {})
        expected_metadata = {
            b"artifact.version": expected.artifact_version.encode(),
            b"system.status": expected.system_status.encode(),
            b"usage.scope": expected.usage_scope.encode(),
            b"market": expected.market.encode(),
            b"horizon": str(expected.horizon).encode(),
            b"benchmark.path": expected.benchmark_path.encode(),
            b"benchmark.semantics": expected.benchmark_semantics.encode(),
            b"prepared_dataset.snapshot_sha256": (
                expected.prepared_dataset_snapshot_sha256.encode()
            ),
            b"daily_archive.snapshot_sha256": (
                expected.daily_archive_snapshot_sha256.encode()
            ),
            b"current_identity.snapshot_sha256": (
                expected.current_identity_snapshot_sha256.encode()
            ),
            b"feature_artifact.sha256": expected.feature_artifact_sha256.encode(),
            b"calendar.snapshot_sha256": expected.calendar_snapshot_sha256.encode(),
            b"benchmark.snapshot_sha256": expected.benchmark_snapshot_sha256.encode(),
            b"benchmark.id": expected.benchmark_id.encode(),
            b"benchmark.version": expected.benchmark_version.encode(),
            b"dataset.snapshot_id": expected.dataset_snapshot_id.encode(),
            b"source.hash": expected.source_hash.encode(),
            b"feature.schema_hash": expected.feature_schema_hash.encode(),
            b"label.version": expected.label_version.encode(),
            b"cost.profile_version": expected.cost_profile_version.encode(),
            b"reason_codes.encoding": b"canonical-json-v1",
        }
        optional_source_metadata = {
            b"feature.source_run_id": expected.feature_source_run_id,
            b"feature.source_run_sha": expected.feature_source_run_sha,
            b"feature.source_artifact_id": expected.feature_source_artifact_id,
            b"feature.source_artifact_digest": (
                expected.feature_source_artifact_digest
            ),
        }
        expected_metadata.update(
            {
                key: value.encode()
                for key, value in optional_source_metadata.items()
                if value is not None
            }
        )
        if (
            table.num_rows != expected.row_count
            or _schema_digest(table.schema) != expected.schema_sha256
            or any(
                observed_result_metadata.get(key) != value
                for key, value in expected_metadata.items()
            )
            or any(
                value is None and key in observed_result_metadata
                for key, value in optional_source_metadata.items()
            )
        ):
            raise PreparedResearchArtifactError(
                "PREPARED_RESEARCH_ARTIFACT_MANIFEST_MISMATCH",
                "Prepared research bytes do not match their manifest",
            )
        return dataset


__all__ = [
    "PREPARED_ARTIFACT_VERSION",
    "PreparedResearchArtifactError",
    "PreparedResearchArtifactManifest",
    "PreparedResearchArtifactWriter",
]
