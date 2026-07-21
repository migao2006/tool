"""Validated input contract for venue-scoped five-day research datasets.

This module deliberately accepts only already assembled, auditable rows.  It
does not read R2, Supabase, or provider APIs; those concerns remain in data
repositories and dataset builders.
"""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportGeneralTypeIssues=false
# pyright: reportAttributeAccessIssue=false

# pyright: reportUnknownLambdaType=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
)
from src.features.price_volume_schema import price_volume_feature_spec
from src.validation.purged_walk_forward import LabeledObservation


TWSE_PRICE_RESEARCH_FEATURES = TWSE_PRICE_VOLUME_FEATURE_NAMES

REQUIRED_RESEARCH_COLUMNS = (
    "symbol",
    "market",
    "horizon",
    "decision_date",
    "decision_at",
    "available_at",
    "source_latest_available_at",
    "availability_basis",
    "entry_at",
    "exit_at",
    "gross_return",
    "net_return",
    "net_alpha",
    "round_trip_cost_rate",
    "direction",
    "data_quality_status",
    "system_status",
    "usage_scope",
    "reason_codes",
    "feature_schema_hash",
    "label_version",
    "benchmark_id",
    "benchmark_version",
    "cost_profile_version",
    "dataset_snapshot_id",
    "source_hash",
)

_PROVENANCE_COLUMNS = (
    "feature_schema_hash",
    "label_version",
    "benchmark_id",
    "benchmark_version",
    "cost_profile_version",
    "dataset_snapshot_id",
    "source_hash",
)


class ResearchDatasetError(ValueError):
    """Raised when prepared rows cannot be safely used for research training."""


def _aware_timestamp(series: Any, name: str) -> Any:
    import pandas as pd

    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    if parsed.isna().any():
        raise ResearchDatasetError(f"{name} must contain timezone-aware timestamps")
    return parsed


def _date_series(series: Any, name: str) -> Any:
    import pandas as pd

    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.isna().any():
        raise ResearchDatasetError(f"{name} must contain valid dates")
    return parsed.dt.date


def _normalized_features_and_required(
    frame: Any,
    feature_names: Sequence[str],
) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(name) for name in feature_names))
    if not normalized or any(not name for name in normalized):
        raise ResearchDatasetError("at least one named research feature is required")
    required = {*REQUIRED_RESEARCH_COLUMNS, *normalized}
    missing = sorted(required.difference(str(column) for column in frame.columns))
    if missing:
        raise ResearchDatasetError(
            "research training columns are missing: " + ", ".join(missing)
        )
    return normalized


def _normalize_temporal_columns(frame: Any) -> Any:
    prepared = frame.copy()
    prepared["decision_date"] = _date_series(
        prepared["decision_date"], "decision_date"
    )
    for name in (
        "decision_at",
        "available_at",
        "source_latest_available_at",
        "entry_at",
        "exit_at",
    ):
        prepared[name] = _aware_timestamp(prepared[name], name)
    return prepared


def _validate_availability(prepared: Any) -> Any:
    if (prepared["available_at"] > prepared["decision_at"]).any():
        raise ResearchDatasetError("feature available_at exceeds decision_at")
    if (prepared["entry_at"] <= prepared["decision_at"]).any():
        raise ResearchDatasetError("entry_at must follow decision_at")
    if (prepared["exit_at"] < prepared["entry_at"]).any():
        raise ResearchDatasetError("exit_at cannot precede entry_at")

    availability_basis = prepared["availability_basis"].astype(str)
    if not availability_basis.isin(("SOURCE_AVAILABLE_AT", "SCHEDULING_HINT")).all():
        raise ResearchDatasetError("availability_basis is unsupported")
    source_basis = availability_basis == "SOURCE_AVAILABLE_AT"
    if (
        prepared.loc[source_basis, "source_latest_available_at"]
        > prepared.loc[source_basis, "decision_at"]
    ).any():
        raise ResearchDatasetError(
            "source available_at exceeds decision_at without a research hint"
        )
    if not (
        prepared.loc[source_basis, "source_latest_available_at"]
        == prepared.loc[source_basis, "available_at"]
    ).all():
        raise ResearchDatasetError(
            "source availability basis must preserve the source timestamp"
        )
    return availability_basis


def _validate_scope(prepared: Any, pd: Any, *, horizon: int, market: str) -> str:
    horizons = pd.to_numeric(prepared["horizon"], errors="coerce")
    if horizons.isna().any() or not (horizons == horizon).all():
        raise ResearchDatasetError("prepared rows must all use horizon=5")
    normalized_market = market.strip().upper()
    if normalized_market not in {"TWSE", "TPEX"}:
        raise ResearchDatasetError("research dataset market is unsupported")
    if not (prepared["market"].astype(str).str.upper() == normalized_market).all():
        raise ResearchDatasetError(f"prepared rows must belong to {normalized_market}")
    if (
        prepared["symbol"].isna().any()
        or (prepared["symbol"].astype(str).str.strip() == "").any()
    ):
        raise ResearchDatasetError("every research row requires a symbol")
    if (
        prepared["data_quality_status"].astype(str).str.upper() == "HARD_FAIL"
    ).any():
        raise ResearchDatasetError("HARD_FAIL rows must be excluded before training")
    if not (
        prepared["data_quality_status"]
        .astype(str)
        .str.upper()
        .isin({"PASS", "WARN"})
        .all()
    ):
        raise ResearchDatasetError("research rows require PASS or WARN data quality")
    if not (prepared["system_status"].astype(str) == "RESEARCH_ONLY").all():
        raise ResearchDatasetError("prepared research rows cannot be promoted")
    if not (prepared["usage_scope"].astype(str) == "MODEL_RESEARCH_ONLY").all():
        raise ResearchDatasetError("prepared rows require MODEL_RESEARCH_ONLY scope")
    return normalized_market


def _validate_provenance(
    prepared: Any,
    *,
    normalized_market: str,
    feature_schema_hash: str | None,
) -> None:
    for name in _PROVENANCE_COLUMNS:
        values = prepared[name].astype(str).str.strip()
        if (values == "").any() or values.nunique(dropna=False) != 1:
            raise ResearchDatasetError(f"{name} must contain one non-empty batch value")
    expected_schema_hash = (
        feature_schema_hash
        if feature_schema_hash is not None
        else price_volume_feature_spec(normalized_market).schema_hash
    )
    if prepared["feature_schema_hash"].iloc[0] != expected_schema_hash:
        raise ResearchDatasetError("feature_schema_hash does not match frozen schema")


def _normalize_reason_codes(prepared: Any, availability_basis: Any) -> None:
    normalized: list[tuple[str, ...]] = []
    for value in prepared["reason_codes"]:
        if (
            not isinstance(value, (tuple, list))
            or not value
            or any(not isinstance(reason, str) or not reason for reason in value)
        ):
            raise ResearchDatasetError(
                "reason_codes must preserve research limitations"
            )
        normalized.append(tuple(dict.fromkeys(value)))
    prepared["reason_codes"] = normalized
    hint_rows = availability_basis == "SCHEDULING_HINT"
    if any(
        "SCHEDULING_HINT_NOT_OFFICIAL_PIT" not in reasons
        for reasons in prepared.loc[hint_rows, "reason_codes"]
    ):
        raise ResearchDatasetError(
            "scheduling hints require an explicit point-in-time limitation"
        )


def _normalize_labels_and_features(
    prepared: Any,
    pd: Any,
    normalized_features: tuple[str, ...],
) -> None:
    for name in (
        "gross_return",
        "net_return",
        "net_alpha",
        "round_trip_cost_rate",
    ):
        prepared[name] = pd.to_numeric(prepared[name], errors="coerce")
        if (
            prepared[name].isna().any()
            or not prepared[name].map(lambda value: isfinite(float(value))).all()
        ):
            raise ResearchDatasetError(f"{name} must contain finite numeric values")
    if (prepared["round_trip_cost_rate"] < 0).any():
        raise ResearchDatasetError("round_trip_cost_rate cannot be negative")
    directions = prepared["direction"].astype(str).str.upper()
    if not directions.isin({"UP", "NEUTRAL", "DOWN"}).all():
        raise ResearchDatasetError("direction must be UP, NEUTRAL, or DOWN")
    prepared["direction"] = directions

    for name in normalized_features:
        prepared[name] = pd.to_numeric(prepared[name], errors="coerce")
        non_missing = prepared[name].dropna()
        if not non_missing.map(lambda value: isfinite(float(value))).all():
            raise ResearchDatasetError(f"{name} must contain finite values when present")
    if prepared[list(normalized_features)].isna().all(axis=0).any():
        empty_features = [
            name for name in normalized_features if prepared[name].isna().all()
        ]
        raise ResearchDatasetError(
            "features are entirely missing: " + ", ".join(empty_features)
        )


def _sort_unique_rows(prepared: Any) -> None:
    if prepared.duplicated(subset=["symbol", "decision_date"]).any():
        raise ResearchDatasetError("symbol and decision_date must be unique")
    prepared.sort_values(["decision_date", "symbol"], inplace=True)
    prepared.reset_index(drop=True, inplace=True)


@dataclass(frozen=True)
class PreparedResearchDataset:
    """A fail-closed single-venue frame plus its immutable feature contract."""

    frame: Any
    feature_names: tuple[str, ...]

    @classmethod
    def from_frame(
        cls,
        frame: Any,
        *,
        feature_names: Sequence[str] = TWSE_PRICE_RESEARCH_FEATURES,
        horizon: int = 5,
        market: str = "TWSE",
        feature_schema_hash: str | None = None,
    ) -> "PreparedResearchDataset":
        try:
            import pandas as pd
        except ModuleNotFoundError as error:  # pragma: no cover - project dependency
            raise ResearchDatasetError(
                "pandas is required for research training"
            ) from error
        if not isinstance(frame, pd.DataFrame):
            raise ResearchDatasetError(
                "research training input must be a pandas DataFrame"
            )
        if frame.empty:
            raise ResearchDatasetError("research training input cannot be empty")

        normalized_features = _normalized_features_and_required(frame, feature_names)
        prepared = _normalize_temporal_columns(frame)
        availability_basis = _validate_availability(prepared)
        normalized_market = _validate_scope(
            prepared,
            pd,
            horizon=horizon,
            market=market,
        )
        _validate_provenance(
            prepared,
            normalized_market=normalized_market,
            feature_schema_hash=feature_schema_hash,
        )
        _normalize_reason_codes(prepared, availability_basis)
        _normalize_labels_and_features(prepared, pd, normalized_features)
        _sort_unique_rows(prepared)
        return cls(frame=prepared, feature_names=normalized_features)

    def observations(self) -> tuple[LabeledObservation, ...]:
        return tuple(
            LabeledObservation(
                sample_id=f"{row.symbol}:{row.decision_date.isoformat()}",
                decision_date=row.decision_date,
                entry_at=row.entry_at.to_pydatetime(),
                exit_at=row.exit_at.to_pydatetime(),
            )
            for row in self.frame[
                ["symbol", "decision_date", "entry_at", "exit_at"]
            ].itertuples(index=False)
        )

    @property
    def decision_dates(self) -> tuple[date, ...]:
        return tuple(self.frame["decision_date"])

    @property
    def latest_training_date(self) -> date:
        return max(self.decision_dates)

    @property
    def latest_decision_at(self) -> datetime:
        return max(value.to_pydatetime() for value in self.frame["decision_at"])

    @property
    def provenance(self) -> dict[str, str]:
        """Return the immutable batch identifiers written into model reports."""

        return {name: str(self.frame[name].iloc[0]) for name in _PROVENANCE_COLUMNS}
