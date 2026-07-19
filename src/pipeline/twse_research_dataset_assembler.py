"""Conservative five-session TWSE research-label assembly.

This is deliberately not the formal :mod:`src.labels.label_factory`.  It can
turn already validated, research-only raw bars and feature rows into a dataset
for an exploratory walk-forward run, while preserving every limitation needed
to prevent accidental production promotion.
"""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from collections import Counter
import pandas as pd

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)
from src.labels.direction_label import NoTradeBandConfig
from src.trading.transaction_cost import TransactionCostModel

from .twse_research_assembly_contracts import (
    ResearchAssemblyAudit,
    ResearchRowExclusion,
    TwseResearchAssemblyResult,
)
from .twse_research_assembly_inputs import (
    ResearchAssemblyInputError,
    bar_frame,
    benchmark_levels,
    date_value,
    empty_prepared,
    feature_records,
    intervals,
)
from .twse_research_row_assembler import (
    HORIZON,
    LABEL_VERSION,
    RowAssemblyContext,
    assemble_research_row,
)


_BASE_AUDIT_REASONS = (
    "UNADJUSTED_PRICE_RESEARCH_ONLY",
    "FORMAL_LABEL_FACTORY_NOT_USED",
)


def assemble_twse_research_dataset(
    *,
    raw_bars: object,
    feature_rows: object,
    benchmark_sessions: object,
    benchmark_id: str,
    benchmark_version: str,
    dataset_snapshot_id: str,
    source_hash: str,
    corporate_action_intervals: object | None = None,
    suspension_intervals: object | None = None,
    transaction_cost_model: TransactionCostModel | None = None,
    cost_profile: str = "base_cost",
    no_trade_band_config: NoTradeBandConfig | None = None,
    corporate_action_history_verified: bool = False,
    security_state_history_verified: bool = False,
    feature_point_in_time_verified: bool = False,
) -> TwseResearchAssemblyResult:
    """Assemble conservative labels without asserting formal PIT eligibility."""

    provenance = (benchmark_id, benchmark_version, dataset_snapshot_id, source_hash)
    if any(not value.strip() for value in provenance):
        raise ResearchAssemblyInputError("dataset and benchmark provenance is required")
    features = feature_records(feature_rows)
    bars, duplicate_bar_keys = bar_frame(raw_bars)
    benchmark, duplicate_benchmark_dates = benchmark_levels(benchmark_sessions)
    sessions = benchmark.sessions
    session_positions = {session: position for position, session in enumerate(sessions)}
    actions = intervals(corporate_action_intervals, "KNOWN_CORPORATE_ACTION_WINDOW")
    suspensions = intervals(suspension_intervals, "KNOWN_SUSPENSION_WINDOW")
    cost_model = transaction_cost_model or TransactionCostModel()
    band_config = no_trade_band_config or NoTradeBandConfig(horizon=HORIZON)
    if band_config.horizon != HORIZON:
        raise ResearchAssemblyInputError("no-trade band must use horizon=5")

    feature_keys = [
        (str(row["symbol"]).strip(), date_value(row["decision_date"], "decision_date"))
        for row in features
    ]
    duplicate_feature_keys = {
        key for key, count in Counter(feature_keys).items() if count > 1
    }
    audit_reasons: list[str] = list(_BASE_AUDIT_REASONS)
    if benchmark.path == "T_PLUS_ONE_OPEN_TO_H_CLOSE":
        audit_reasons.append("BENCHMARK_PRICE_INDEX_NOT_TOTAL_RETURN")
    else:
        audit_reasons.append("BENCHMARK_CLOSE_TO_CLOSE_NOT_EXECUTION_PATH_ALIGNED")
    if not corporate_action_history_verified:
        audit_reasons.append("COMPANY_ACTION_HISTORY_INCOMPLETE")
    if not security_state_history_verified:
        audit_reasons.append("SECURITY_STATE_HISTORY_INCOMPLETE")
    if not feature_point_in_time_verified:
        audit_reasons.append("HISTORICAL_FEATURE_AVAILABILITY_UNVERIFIED")
    context = RowAssemblyContext(
        bars=bars,
        duplicate_bar_keys=duplicate_bar_keys,
        benchmark=benchmark,
        duplicate_benchmark_dates=duplicate_benchmark_dates,
        sessions=sessions,
        session_positions=session_positions,
        actions=actions,
        suspensions=suspensions,
        cost_model=cost_model,
        cost_profile=cost_profile,
        band_config=band_config,
        duplicate_feature_keys=duplicate_feature_keys,
        benchmark_id=benchmark_id,
        benchmark_version=benchmark_version,
        dataset_snapshot_id=dataset_snapshot_id,
        source_hash=source_hash,
        research_reason_codes=tuple(audit_reasons),
    )
    prepared: list[dict[str, object]] = []
    exclusions: list[ResearchRowExclusion] = []
    scheduling_hint_count = 0

    for feature, (symbol, decision_date) in zip(features, feature_keys, strict=True):
        outcome = assemble_research_row(
            feature,
            symbol=symbol,
            decision_date=decision_date,
            context=context,
        )
        scheduling_hint_count += outcome.scheduling_hint_used
        if outcome.prepared_row is not None:
            prepared.append(outcome.prepared_row)
        if outcome.exclusion is not None:
            exclusions.append(outcome.exclusion)

    prepared_frame = pd.DataFrame(prepared) if prepared else empty_prepared()
    if not prepared_frame.empty:
        prepared_frame.sort_values(["decision_date", "symbol"], inplace=True)
        prepared_frame.reset_index(drop=True, inplace=True)
    reason_counts = Counter(
        reason for exclusion in exclusions for reason in exclusion.reason_codes
    )
    if scheduling_hint_count:
        audit_reasons.append("SCHEDULING_HINT_NOT_OFFICIAL_PIT")
    audit = ResearchAssemblyAudit(
        input_feature_row_count=len(features),
        prepared_row_count=len(prepared),
        excluded_row_count=len(exclusions),
        reason_counts=dict(sorted(reason_counts.items())),
        audit_reason_codes=tuple(audit_reasons),
        corporate_action_history_verified=corporate_action_history_verified,
        security_state_history_verified=security_state_history_verified,
        feature_point_in_time_verified=feature_point_in_time_verified,
        scheduling_hint_row_count=scheduling_hint_count,
        feature_schema_hash=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        label_version=LABEL_VERSION,
        benchmark_id=benchmark_id,
        benchmark_version=benchmark_version,
        cost_profile_version=f"{cost_model.config.version}:{cost_profile}",
        dataset_snapshot_id=dataset_snapshot_id,
        source_hash=source_hash,
    )
    return TwseResearchAssemblyResult(
        prepared_rows=prepared_frame,
        exclusions=tuple(exclusions),
        audit=audit,
    )


__all__ = [
    "ResearchAssemblyInputError",
    "assemble_twse_research_dataset",
]
