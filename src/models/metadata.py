from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.core.horizon import require_supported_horizon


@dataclass(frozen=True)
class ModelMetadata:
    model_family: str
    horizon: int
    model_version: str
    feature_schema_hash: str
    training_end_date: date
    benchmark_version: str | None
    cost_profile_version: str | None
    validation_status: str
    artifact_filename: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        require_supported_horizon(self.horizon)
        if self.validation_status not in {"PASS", "RESEARCH_ONLY", "FAIL"}:
            raise ValueError("invalid validation_status")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

    def eligible_at(self, decision_at: datetime) -> bool:
        """Prevent daily inference from loading an artifact created in the future."""

        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("decision_at must be timezone-aware")
        return self.created_at <= decision_at and self.training_end_date <= decision_at.date()

    def save(self, root: str | Path) -> Path:
        target_dir = Path(root) / f"horizon_{self.horizon}" / self.model_family.lower()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "metadata.json"
        payload: dict[str, Any] = asdict(self)
        payload["training_end_date"] = self.training_end_date.isoformat()
        payload["created_at"] = self.created_at.isoformat()
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return target
