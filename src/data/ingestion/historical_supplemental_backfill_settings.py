"""Dataset access policy for the FinMind supplemental-history worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from .historical_supplemental_contracts import SUPPLEMENTAL_DATASETS


FREE_TIER_SUPPLEMENTAL_DATASETS = (
    "institutional_flows",
    "margin_short",
)
_ENVIRONMENT_NAME = "HISTORICAL_SUPPLEMENTAL_ALLOWED_DATASETS"


@dataclass(frozen=True)
class HistoricalSupplementalBackfillSettings:
    """Datasets one provider credential is allowed to claim."""

    allowed_datasets: tuple[str, ...] = FREE_TIER_SUPPLEMENTAL_DATASETS

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> "HistoricalSupplementalBackfillSettings":
        values = os.environ if environment is None else environment
        raw = values.get(
            _ENVIRONMENT_NAME,
            ",".join(FREE_TIER_SUPPLEMENTAL_DATASETS),
        )
        allowed = tuple(part.strip() for part in raw.split(",") if part.strip())
        return cls(allowed_datasets=allowed)

    def __post_init__(self) -> None:
        if not self.allowed_datasets:
            raise ValueError(f"{_ENVIRONMENT_NAME} must contain at least one dataset")
        if len(set(self.allowed_datasets)) != len(self.allowed_datasets):
            raise ValueError(f"{_ENVIRONMENT_NAME} must not contain duplicates")
        unsupported = set(self.allowed_datasets).difference(SUPPLEMENTAL_DATASETS)
        if unsupported:
            raise ValueError(
                f"{_ENVIRONMENT_NAME} contains unsupported datasets: "
                + ", ".join(sorted(unsupported))
            )
