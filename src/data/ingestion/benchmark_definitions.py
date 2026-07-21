"""Build versioned benchmark definitions from verified source contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json

from src.data.providers.contracts import ProviderPayload

from .benchmark_contracts import (
    BENCHMARK_REASON_CODES,
    BENCHMARK_SPECS,
    BENCHMARK_VERSION,
)
from .contracts import IngestionError


def _contract_hash(contract: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(contract),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def benchmark_definition_rows(
    *,
    payloads: Mapping[str, ProviderPayload],
    observations: Mapping[str, Sequence[Mapping[str, object]]],
    source_ids: Mapping[str, int],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for market in ("TWSE", "TPEX"):
        spec = BENCHMARK_SPECS[market]
        payload = payloads[market]
        market_observations = observations[market]
        if not market_observations:
            raise IngestionError(
                "BENCHMARK_COVERAGE_EMPTY",
                f"{market} total-return index did not return any observations",
            )
        effective_from = min(
            str(row["observation_at"])[:10] for row in market_observations
        )
        contract: dict[str, object] = {
            "benchmark_code": spec.series_code,
            "benchmark_version": BENCHMARK_VERSION,
            "market": market,
            "index_symbol": spec.series_code,
            "source_dataset": spec.dataset,
            "return_basis": "TOTAL_RETURN_INDEX",
            "observation_frequency": "DAILY_CLOSE",
            "return_convention": "CLOSE_TO_CLOSE",
            "target_trade_path": "T_PLUS_1_OPEN_TO_H_CLOSE",
            "alignment_status": "RESEARCH_ONLY",
            "usage_scope": "LABEL_TARGET_ONLY",
            "system_status": "RESEARCH_ONLY",
        }
        rows.append(
            {
                **contract,
                "effective_from": effective_from,
                "effective_to": None,
                "available_at": payload.retrieved_at.isoformat(),
                "source_id": source_ids[market],
                "source_version": payload.source_version,
                "source_revision_hash": _contract_hash(contract),
                "reason_codes": list(BENCHMARK_REASON_CODES),
                "metadata": {
                    "remote_field": spec.remote_field,
                    "source_url": payload.source_url,
                    "history_scope": "CURRENT_MONTH_ENDPOINT_ONLY",
                    "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
                },
            }
        )
    return rows
