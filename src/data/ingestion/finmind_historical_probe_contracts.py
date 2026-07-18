"""Audit-only output contracts for the bounded FinMind historical probe."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinMindQuotaSummary:
    requests_used: int
    request_limit: int
    requests_remaining: int
    response_sha256: str


@dataclass(frozen=True)
class FinMindSymbolProbe:
    symbol: str
    rows: int
    minimum_date: str | None
    maximum_date: str | None
    unique_symbols: int
    response_bytes: int
    response_encoding: str
    response_sha256: str
    suspected_truncation: bool
    truncation_reasons: tuple[str, ...]


@dataclass(frozen=True)
class FinMindHistoricalProbeSummary:
    status: str
    provider: str
    remote_dataset: str
    start_date: str
    end_date: str
    requested_symbols: tuple[str, ...]
    pacing_seconds: float
    quota: FinMindQuotaSummary
    symbols: tuple[FinMindSymbolProbe, ...]
    total_rows: int
    coverage_assessment: str = "HEURISTIC_ONLY_NOT_TRAINING_READY"
    writes_performed: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "remote_dataset": self.remote_dataset,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "requested_symbols": list(self.requested_symbols),
            "pacing_seconds": self.pacing_seconds,
            "quota": {
                "requests_used": self.quota.requests_used,
                "request_limit": self.quota.request_limit,
                "requests_remaining": self.quota.requests_remaining,
                "response_sha256": self.quota.response_sha256,
            },
            "symbols": [
                {
                    "symbol": result.symbol,
                    "rows": result.rows,
                    "minimum_date": result.minimum_date,
                    "maximum_date": result.maximum_date,
                    "unique_symbols": result.unique_symbols,
                    "response_bytes": result.response_bytes,
                    "response_encoding": result.response_encoding,
                    "response_sha256": result.response_sha256,
                    "suspected_truncation": result.suspected_truncation,
                    "truncation_reasons": list(result.truncation_reasons),
                }
                for result in self.symbols
            ],
            "total_rows": self.total_rows,
            "coverage_assessment": self.coverage_assessment,
            "writes_performed": self.writes_performed,
        }
