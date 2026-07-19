"""Frozen manifest contract for prepared TWSE research artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re


PREPARED_ARTIFACT_VERSION = "twse-prepared-research-5d.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PreparedResearchArtifactError(RuntimeError):
    """Stable artifact failure without row data or filesystem details."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


@dataclass(frozen=True)
class PreparedResearchArtifactManifest:
    parquet_sha256: str
    schema_sha256: str
    byte_size: int
    row_count: int
    dataset_snapshot_id: str
    source_hash: str
    benchmark_snapshot_sha256: str
    benchmark_id: str
    benchmark_version: str
    feature_schema_hash: str
    label_version: str
    cost_profile_version: str
    horizon: int = 5
    market: str = "TWSE"
    benchmark_path: str = "T_PLUS_ONE_OPEN_TO_H_CLOSE"
    benchmark_semantics: str = "PRICE_INDEX_NOT_TOTAL_RETURN"
    usage_scope: str = "MODEL_RESEARCH_ONLY"
    system_status: str = "RESEARCH_ONLY"
    artifact_version: str = PREPARED_ARTIFACT_VERSION

    def __post_init__(self) -> None:
        hashes = (
            self.parquet_sha256,
            self.schema_sha256,
            self.source_hash,
            self.benchmark_snapshot_sha256,
            self.feature_schema_hash,
        )
        if any(_SHA256.fullmatch(value) is None for value in hashes):
            raise ValueError("prepared artifact contains an invalid SHA-256")
        if self.byte_size <= 0 or self.row_count <= 0:
            raise ValueError("prepared artifact byte and row counts must be positive")
        if (
            self.horizon != 5
            or self.market != "TWSE"
            or self.benchmark_path != "T_PLUS_ONE_OPEN_TO_H_CLOSE"
            or self.benchmark_semantics != "PRICE_INDEX_NOT_TOTAL_RETURN"
            or self.usage_scope != "MODEL_RESEARCH_ONLY"
            or self.system_status != "RESEARCH_ONLY"
            or self.artifact_version != PREPARED_ARTIFACT_VERSION
        ):
            raise ValueError("prepared artifact exceeds the research-only contract")
        text = (
            self.dataset_snapshot_id,
            self.benchmark_id,
            self.benchmark_version,
            self.label_version,
            self.cost_profile_version,
        )
        if any(not value.strip() for value in text):
            raise ValueError("prepared artifact provenance is incomplete")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


__all__ = [
    "PREPARED_ARTIFACT_VERSION",
    "PreparedResearchArtifactError",
    "PreparedResearchArtifactManifest",
]
