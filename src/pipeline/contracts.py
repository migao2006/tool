"""Dependency-light contracts shared by every pipeline entry point."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from src.config.types import MvpConfig
from src.core.horizon import require_production_horizon

from .promotion import REQUIRED_MODEL_ARTIFACTS


class PipelineMode(str, Enum):
    TRAIN = "train"
    BACKTEST = "backtest"
    INFER = "infer"


class PipelineStatus(str, Enum):
    PASS = "PASS"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    FAIL = "FAIL"


def _empty_source_metadata() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class PipelineBatch:
    """Actual records plus immutable provenance from a file or repository."""

    records: Any
    source_uri: str
    source_hash: str | None = None
    source_metadata: Mapping[str, object] = field(
        default_factory=_empty_source_metadata
    )
    loaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.source_uri.strip():
            raise ValueError("source_uri is required")
        if self.loaded_at.tzinfo is None or self.loaded_at.utcoffset() is None:
            raise ValueError("loaded_at must be timezone-aware")


@dataclass(frozen=True)
class PipelineContext:
    mode: PipelineMode
    horizon: int
    config: MvpConfig
    artifact_root: Path
    as_of_date: date | None = None

    def __post_init__(self) -> None:
        require_production_horizon(self.horizon)
        if self.config.horizon != self.horizon:
            raise ValueError(
                f"config horizon={self.config.horizon} does not match requested horizon={self.horizon}"
            )
        if self.mode is PipelineMode.INFER and self.as_of_date is None:
            raise ValueError("daily inference requires as_of_date")


@dataclass(frozen=True)
class PipelineResult:
    mode: PipelineMode
    horizon: int
    status: PipelineStatus
    reason_codes: tuple[str, ...] = ()
    records_read: int = 0
    artifacts: Mapping[str, str] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    source_uri: str | None = None
    source_hash: str | None = None
    run_id: str | None = None
    model_version: str | None = None
    feature_schema_hash: str | None = None
    cost_profile_version: str | None = None
    training_end_date: date | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        require_production_horizon(self.horizon)
        if self.records_read < 0:
            raise ValueError("records_read cannot be negative")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if self.status is PipelineStatus.PASS:
            if self.reason_codes:
                raise ValueError("PASS result cannot contain failure reason codes")
            if self.records_read == 0:
                raise ValueError("PASS result requires audited records")
            if not self.source_uri or not self.source_uri.strip():
                raise ValueError("PASS result requires source_uri")
            if not self.source_hash or not self.source_hash.strip():
                raise ValueError("PASS result requires source_hash")
            for field_name in (
                "run_id",
                "model_version",
                "feature_schema_hash",
                "cost_profile_version",
            ):
                value = getattr(self, field_name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"PASS result requires {field_name}")
            if self.training_end_date is None:
                raise ValueError("PASS result requires training_end_date")
            if not self.artifacts:
                raise ValueError("PASS result requires model artifacts")
            missing_artifacts = set(REQUIRED_MODEL_ARTIFACTS).difference(self.artifacts)
            if missing_artifacts:
                raise ValueError(
                    "PASS result is missing required artifacts: "
                    + ", ".join(sorted(missing_artifacts))
                )
            if any(
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(uri, str)
                or not uri.strip()
                for name, uri in self.artifacts.items()
            ):
                raise ValueError("PASS result requires named artifact locations")
            if not self.metrics:
                raise ValueError("PASS result requires validation metrics")
        elif not self.reason_codes:
            raise ValueError("non-PASS result requires reason codes")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        payload["status"] = self.status.value
        payload["generated_at"] = self.generated_at.isoformat()
        if self.training_end_date is not None:
            payload["training_end_date"] = self.training_end_date.isoformat()
        return payload

    @property
    def exit_code(self) -> int:
        return {
            PipelineStatus.PASS: 0,
            PipelineStatus.FAIL: 1,
            PipelineStatus.RESEARCH_ONLY: 2,
        }[self.status]


@runtime_checkable
class DatasetRepository(Protocol):
    """Repository contract suitable for files, Supabase, or a data lake."""

    def load(
        self,
        *,
        mode: PipelineMode,
        horizon: int,
        as_of_date: date | None,
    ) -> PipelineBatch: ...


@runtime_checkable
class PipelineRunner(Protocol):
    """Loose adapter around model and backtest implementations."""

    def train(
        self, batch: PipelineBatch, context: PipelineContext
    ) -> PipelineResult: ...

    def backtest(
        self, batch: PipelineBatch, context: PipelineContext
    ) -> PipelineResult: ...

    def infer(
        self, batch: PipelineBatch, context: PipelineContext
    ) -> PipelineResult: ...
