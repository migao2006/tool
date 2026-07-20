"""Frozen venue identity for the shared price research procedure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VenuePriceResearchProfile:
    """Immutable venue differences around one shared research procedure."""

    market: str
    scope: str
    model_version: str
    feature_schema_hash: str
    feature_names: tuple[str, ...]
    expected_label_version: str
    expected_benchmark_id: str
    primary_reason_code: str
    dataset_invalid_reason_code: str
    artifact_stem: str
    bundle_unavailable_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.market not in {"TWSE", "TPEX"}:
            raise ValueError("price research supports only TWSE or TPEX")
        text = (
            self.scope,
            self.model_version,
            self.expected_label_version,
            self.expected_benchmark_id,
            self.primary_reason_code,
            self.dataset_invalid_reason_code,
            self.artifact_stem,
        )
        if any(not value.strip() for value in text):
            raise ValueError("price research profile text fields are required")
        if len(self.feature_schema_hash) != 64 or any(
            value not in "0123456789abcdef" for value in self.feature_schema_hash
        ):
            raise ValueError("feature_schema_hash must be a lowercase SHA-256")
        if not self.feature_names or len(set(self.feature_names)) != len(
            self.feature_names
        ):
            raise ValueError("feature_names must be non-empty and unique")

    @property
    def fold_scope_prefix(self) -> str:
        return f"{self.market.lower()}-research"


__all__ = ["VenuePriceResearchProfile"]
