"""Explicitly gated publisher for venue-isolated research JSON artifacts."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import re
from typing import cast, final

from src.data.research.twse_research_prediction_supabase_contracts import (
    ResearchSupabasePublishResult,
    SupabaseResearchWriter,
)
from src.data.research.twse_research_decision_gate_repository import (
    persist_research_decision_gates,
)
from src.data.research.twse_research_prediction_supabase_payload import (
    ParsedResearchSnapshot,
    parse_research_snapshot,
    resolve_research_snapshot,
)


def _required(payload: Mapping[str, object], name: str) -> object:
    value = payload.get(name)
    if value is None or value == "":
        raise ValueError(f"research prediction artifact is missing {name}")
    return value


_COST_PROFILE_CORE_FIELDS = (
    "cost_profile_version",
    "asset_type",
    "commission_rate",
    "commission_discount",
    "minimum_fee",
    "sell_tax_rate",
    "estimated_order_notional_ntd",
    "spread_model",
    "slippage_scenario",
    "market_impact_parameter",
    "max_adv_participation",
)
_COST_PROFILE_NUMERIC_FIELDS = frozenset(
    {
        "commission_rate",
        "commission_discount",
        "minimum_fee",
        "sell_tax_rate",
        "estimated_order_notional_ntd",
        "market_impact_parameter",
        "max_adv_participation",
    }
)


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"cost profile {field_name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"cost profile {field_name} must be numeric") from error
    if not parsed.is_finite():
        raise ValueError(f"cost profile {field_name} must be finite")
    return parsed


def _cost_profile_mismatches(
    expected: Mapping[str, object], actual: Mapping[str, object]
) -> tuple[str, ...]:
    mismatches: list[str] = []
    for field_name in _COST_PROFILE_CORE_FIELDS:
        expected_value = expected[field_name]
        actual_value = actual.get(field_name)
        if field_name in _COST_PROFILE_NUMERIC_FIELDS:
            try:
                values_match = _decimal(expected_value, field_name) == _decimal(
                    actual_value, field_name
                )
            except ValueError:
                values_match = False
        else:
            values_match = (
                isinstance(expected_value, str)
                and isinstance(actual_value, str)
                and actual_value == expected_value
            )
        if not values_match:
            mismatches.append(field_name)
    return tuple(mismatches)


class TwseResearchPredictionSupabasePublisher:
    """Write one expected venue only after explicit environment gates."""

    def __init__(
        self,
        writer: SupabaseResearchWriter,
        *,
        target_environment: str,
        publish_enabled: bool,
        production_publish_enabled: bool = False,
        expected_market: str = "TWSE",
    ) -> None:
        environment = target_environment.strip().lower()
        if not publish_enabled:
            raise ValueError("RESEARCH_PREDICTION_SUPABASE_PUBLISH_ENABLED is false")
        if environment not in {"development", "staging", "production"}:
            raise ValueError(
                "research prediction publishing requires a recognized environment"
            )
        if environment == "production" and not production_publish_enabled:
            raise ValueError("RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED is false")
        market = expected_market.strip().upper()
        if market not in {"TWSE", "TPEX"}:
            raise ValueError("research prediction publisher market is unsupported")
        self.writer = writer
        self.target_environment = environment
        self.expected_market = market

    def publish(
        self,
        payload: Mapping[str, object],
    ) -> ResearchSupabasePublishResult:
        parsed = parse_research_snapshot(payload)
        if parsed.market != self.expected_market:
            raise ValueError("research snapshot market does not match its publisher")
        security_ids = self._security_ids(parsed.predictions, parsed.market)
        resolved = resolve_research_snapshot(parsed, security_ids)
        self._ensure_cost_profile(payload)
        response = self.writer.rpc(
            "publish_research_prediction_snapshot",
            {
                "p_run": dict(resolved.run),
                "p_stock_predictions": [
                    dict(value) for value in resolved.stock_predictions
                ],
            },
        )
        run_id, prediction_count = self._parse_rpc_result(response, parsed)
        gate_count = persist_research_decision_gates(
            self.writer,
            prediction_run_id=run_id,
            stock_predictions=resolved.stock_predictions,
            decision_gates=resolved.decision_gates,
        )
        return ResearchSupabasePublishResult(
            prediction_run_id=run_id,
            prediction_count=prediction_count,
            target_environment=self.target_environment,
            decision_gate_count=gate_count,
        )

    def _security_ids(
        self,
        predictions: Sequence[Mapping[str, object]],
        market: str,
    ) -> dict[str, int]:
        symbols = tuple(str(_required(value, "symbol")) for value in predictions)
        if len(set(symbols)) != len(symbols):
            raise ValueError("research prediction symbols must be unique")
        if any(re.fullmatch(r"[0-9A-Z]{2,12}", symbol) is None for symbol in symbols):
            raise ValueError("research prediction contains an unsafe symbol")
        escaped = list(symbols)
        records: list[dict[str, object]] = []
        for offset in range(0, len(escaped), 200):
            batch = escaped[offset : offset + 200]
            records.extend(
                self.writer.select_rows(
                    "securities",
                    select="security_id,symbol,market,asset_type",
                    filters={
                        "market": f"eq.{market}",
                        "asset_type": "eq.COMMON_STOCK",
                        "symbol": f"in.({','.join(batch)})",
                    },
                    limit=len(batch),
                )
            )
        mapping = {
            str(row["symbol"]): int(cast(int | str, row["security_id"]))
            for row in records
            if row.get("market") == market and row.get("asset_type") == "COMMON_STOCK"
        }
        missing = sorted(set(symbols).difference(mapping))
        if missing:
            raise ValueError(
                "research prediction securities are unresolved: " + ", ".join(missing)
            )
        return mapping

    def _ensure_cost_profile(self, payload: Mapping[str, object]) -> None:
        metadata_value = payload.get("cost_metadata")
        if not isinstance(metadata_value, Mapping):
            raise ValueError("research prediction cost_metadata must be an object")
        metadata = cast(Mapping[str, object], metadata_value)
        fields = (
            "asset_type",
            "commission_rate",
            "commission_discount",
            "minimum_fee",
            "sell_tax_rate",
            "estimated_order_notional_ntd",
            "spread_model",
            "slippage_scenario",
            "market_impact_parameter",
            "max_adv_participation",
        )
        row = {name: _required(metadata, name) for name in fields}
        version = str(_required(payload, "cost_profile_version"))
        if not version.strip():
            raise ValueError("cost_profile_version must not be blank")
        row["cost_profile_version"] = version
        # Snapshot identity belongs on prediction_runs. New profiles keep the
        # generic legacy metadata object empty; cost identity is verified from the
        # typed execution columns above.
        row["parameters"] = {}
        _ = self.writer.upsert(
            "cost_profiles",
            [row],
            on_conflict="cost_profile_version",
            preserve_existing=True,
        )
        stored = self.writer.select_rows(
            "cost_profiles",
            select=",".join(_COST_PROFILE_CORE_FIELDS),
            filters={"cost_profile_version": f"eq.{version}"},
            limit=2,
        )
        if len(stored) != 1:
            raise ValueError(
                "cost profile insert-or-read verification did not return one row"
            )
        mismatches = _cost_profile_mismatches(row, stored[0])
        if mismatches:
            raise ValueError(
                "cost profile version has different immutable parameters: "
                + ", ".join(mismatches)
            )

    @staticmethod
    def _parse_rpc_result(
        response: object, parsed: ParsedResearchSnapshot
    ) -> tuple[int, int]:
        if not isinstance(response, Mapping):
            raise ValueError("Supabase atomic publisher returned an invalid response")
        try:
            run_id = int(cast(int | str, response["prediction_run_id"]))
            prediction_count = int(cast(int | str, response["prediction_count"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Supabase atomic publisher returned an invalid response"
            ) from error
        if run_id < 1 or prediction_count != len(parsed.predictions):
            raise ValueError(
                "Supabase atomic publisher returned an unexpected row count"
            )
        if response.get("market_scope") != parsed.market:
            raise ValueError(
                "Supabase atomic publisher returned an unexpected market scope"
            )
        return run_id, prediction_count


@final
class TpexResearchPredictionSupabasePublisher(TwseResearchPredictionSupabasePublisher):
    """TPEX adapter retaining the same explicit two-gate Production policy."""

    def __init__(
        self,
        writer: SupabaseResearchWriter,
        *,
        target_environment: str,
        publish_enabled: bool,
        production_publish_enabled: bool = False,
    ) -> None:
        super().__init__(
            writer,
            target_environment=target_environment,
            publish_enabled=publish_enabled,
            production_publish_enabled=production_publish_enabled,
            expected_market="TPEX",
        )


__all__ = [
    "ResearchSupabasePublishResult",
    "TpexResearchPredictionSupabasePublisher",
    "TwseResearchPredictionSupabasePublisher",
]
