"""Audit-only contracts for the bounded Fugle adjusted-price probe."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FugleCandleSeriesProbe:
    adjusted: bool
    row_count: int
    minimum_date: str
    maximum_date: str
    response_sha256: str
    source_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "adjusted": self.adjusted,
            "row_count": self.row_count,
            "minimum_date": self.minimum_date,
            "maximum_date": self.maximum_date,
            "response_sha256": self.response_sha256,
            "source_version": self.source_version,
        }


@dataclass(frozen=True)
class FugleAdjustedProbeSummary:
    symbol: str
    start_date: str
    end_date: str
    raw: FugleCandleSeriesProbe
    adjusted: FugleCandleSeriesProbe
    comparable_date_count: int
    differing_date_count: int
    raw_only_date_count: int
    adjusted_only_date_count: int
    interpretation: str
    status: str = "RESEARCH_ONLY"
    provider: str = "FUGLE"
    remote_dataset: str = "historical_candles"
    adjusted_access_confirmed: bool = True
    economic_validation_status: str = "NOT_VALIDATED"
    usage_scope: str = "CAPABILITY_PROBE_ONLY"
    training_ready: bool = False
    writes_performed: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "remote_dataset": self.remote_dataset,
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "raw": self.raw.to_dict(),
            "adjusted": self.adjusted.to_dict(),
            "adjusted_access_confirmed": self.adjusted_access_confirmed,
            "comparable_date_count": self.comparable_date_count,
            "differing_date_count": self.differing_date_count,
            "raw_only_date_count": self.raw_only_date_count,
            "adjusted_only_date_count": self.adjusted_only_date_count,
            "interpretation": self.interpretation,
            "economic_validation_status": self.economic_validation_status,
            "usage_scope": self.usage_scope,
            "training_ready": self.training_ready,
            "writes_performed": self.writes_performed,
        }
