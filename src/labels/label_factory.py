"""Single source of truth for executable forward-return labels.

Signals are made after all allowed data for session ``t`` are available, enter at
the next exchange session's executable open and exit at the close of the ``h``-th
held exchange session. The production model currently permits only ``h=5``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from src.core.horizon import PRODUCTION_HORIZON

from .contracts import (
    CorporateAction,
    CorporateActionCoverage,
    ExecutablePrice,
    LabelDataError,
    LabelResult,
    LabelWindow,
    LookAheadError,
    ONE,
    decimal_label_value,
    require_aware_datetime,
)
from .corporate_action_return import (
    executable_total_return,
    validate_corporate_action_inputs,
)
from .cost_resolver import resolve_label_cost
from .direction_label import (
    DirectionLabel,
    NoTradeBandConfig,
    make_direction_label,
    make_direction_labels,
    no_trade_band,
)
from .trading_calendar import TradingCalendar

if TYPE_CHECKING:
    from src.trading.transaction_cost import TransactionCostModel


TAIPEI = ZoneInfo("Asia/Taipei")


class LabelFactory:
    """Build common ranking, direction and return-distribution targets."""

    def __init__(
        self,
        calendar: TradingCalendar,
        transaction_cost_model: TransactionCostModel | None = None,
    ) -> None:
        self.calendar: TradingCalendar = calendar
        self.transaction_cost_model: TransactionCostModel | None = (
            transaction_cost_model
        )

    def create(
        self,
        *,
        symbol: str,
        decision_at: datetime,
        entry_open: ExecutablePrice | None,
        exit_close: ExecutablePrice | None,
        benchmark_return: Decimal | int | float | str | None,
        benchmark_id: str,
        benchmark_version: str,
        round_trip_cost_rate: Decimal | int | float | str | None = None,
        cost_profile_version: str | None = None,
        cost_profile: str = "base_cost",
        quantity: Decimal | int | float | str | None = None,
        adv20_ntd: Decimal | int | float | str | None = None,
        feature_available_ats: Mapping[str, datetime] | Iterable[datetime] = (),
        corporate_actions: Iterable[CorporateAction] = (),
        corporate_action_coverage: CorporateActionCoverage | None = None,
        trailing_volatility: float | None = None,
        no_trade_band_config: NoTradeBandConfig | None = None,
        horizon: int = PRODUCTION_HORIZON,
        research: bool = False,
    ) -> LabelResult:
        require_aware_datetime(decision_at, "decision_at")
        self._audit_available_at(feature_available_ats, decision_at)
        if not symbol.strip():
            raise LabelDataError("symbol is required")
        if entry_open is None:
            raise LabelDataError("entry_open is required")
        if exit_close is None:
            raise LabelDataError("exit_close is required")

        window = self.calendar.label_window(
            decision_at.astimezone(TAIPEI).date(),
            horizon=horizon,
            research=research,
        )
        if entry_open.session_date != window.entry_date:
            raise ValueError("entry price must be the t+1 exchange-session open")
        if exit_close.session_date != window.exit_date:
            raise ValueError("exit price must be the h-th held exchange-session close")
        benchmark = self._validate_benchmark(
            benchmark_return,
            benchmark_id,
            benchmark_version,
        )

        actions = tuple(corporate_actions)
        validate_corporate_action_inputs(
            calendar=self.calendar,
            actions=actions,
            coverage=corporate_action_coverage,
            window=window,
        )
        cost_rate, resolved_cost_version, cost_reasons = resolve_label_cost(
            transaction_cost_model=self.transaction_cost_model,
            entry_open=entry_open,
            exit_close=exit_close,
            horizon=horizon,
            round_trip_cost_rate=round_trip_cost_rate,
            cost_profile_version=cost_profile_version,
            cost_profile=cost_profile,
            quantity=quantity,
            adv20_ntd=adv20_ntd,
        )

        execution_reasons = self._execution_reasons(entry_open, side="BUY")
        execution_reasons.extend(self._execution_reasons(exit_close, side="SELL"))
        execution_reasons.extend(cost_reasons)
        if execution_reasons:
            return self._invalid_result(
                symbol=symbol,
                window=window,
                cost_rate=cost_rate,
                cost_profile_version=resolved_cost_version,
                benchmark_id=benchmark_id,
                benchmark_version=benchmark_version,
                reason_codes=execution_reasons,
            )

        gross_return, applied_actions = executable_total_return(
            entry_price=entry_open.decimal_price,
            exit_price=exit_close.decimal_price,
            actions=actions,
            window=window,
        )
        net_return = gross_return - cost_rate
        excess_return = net_return - benchmark
        direction, band, band_version = self._direction_target(
            net_return=net_return,
            horizon=horizon,
            trailing_volatility=trailing_volatility,
            config=no_trade_band_config,
        )
        return LabelResult(
            symbol=symbol,
            window=window,
            valid=True,
            gross_return=gross_return,
            net_return=net_return,
            benchmark_return=benchmark,
            excess_return=excess_return,
            round_trip_cost_rate=cost_rate,
            cost_profile_version=resolved_cost_version,
            benchmark_id=benchmark_id,
            benchmark_version=benchmark_version,
            direction=direction,
            no_trade_band=band,
            no_trade_band_version=band_version,
            reason_codes=(),
            applied_corporate_actions=applied_actions,
        )

    @staticmethod
    def _validate_benchmark(
        benchmark_return: Decimal | int | float | str | None,
        benchmark_id: str,
        benchmark_version: str,
    ) -> Decimal:
        if benchmark_return is None:
            raise LabelDataError("benchmark_return is required")
        benchmark = decimal_label_value(benchmark_return, name="benchmark_return")
        if benchmark <= -ONE:
            raise ValueError("benchmark_return cannot be less than or equal to -1")
        if not benchmark_id or not benchmark_version:
            raise ValueError("benchmark id and version are required for model metadata")
        return benchmark

    @staticmethod
    def _direction_target(
        *,
        net_return: Decimal,
        horizon: int,
        trailing_volatility: float | None,
        config: NoTradeBandConfig | None,
    ) -> tuple[DirectionLabel | None, Decimal | None, str | None]:
        if trailing_volatility is None and config is None:
            return None, None, None
        if trailing_volatility is None or config is None:
            raise LabelDataError(
                "trailing_volatility and no_trade_band_config must be supplied together"
            )
        if config.horizon != horizon:
            raise ValueError("no-trade band horizon must match the label horizon")
        band = no_trade_band(trailing_volatility, config)
        return (
            make_direction_label(float(net_return), trailing_volatility, config),
            Decimal(str(band)),
            config.version,
        )

    @staticmethod
    def _invalid_result(
        *,
        symbol: str,
        window: LabelWindow,
        cost_rate: Decimal,
        cost_profile_version: str,
        benchmark_id: str,
        benchmark_version: str,
        reason_codes: Iterable[str],
    ) -> LabelResult:
        return LabelResult(
            symbol=symbol,
            window=window,
            valid=False,
            gross_return=None,
            net_return=None,
            benchmark_return=None,
            excess_return=None,
            round_trip_cost_rate=cost_rate,
            cost_profile_version=cost_profile_version,
            benchmark_id=benchmark_id,
            benchmark_version=benchmark_version,
            direction=None,
            no_trade_band=None,
            no_trade_band_version=None,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            applied_corporate_actions=(),
        )

    @staticmethod
    def _audit_available_at(
        feature_available_ats: Mapping[str, datetime] | Iterable[datetime],
        decision_at: datetime,
    ) -> None:
        late: list[str] = []
        if isinstance(feature_available_ats, Mapping):
            named_available_ats = cast(
                Mapping[str, datetime],
                feature_available_ats,
            )
            for name, available_at in named_available_ats.items():
                require_aware_datetime(available_at, f"available_at[{name}]")
                if available_at > decision_at:
                    late.append(name)
        else:
            for index, available_at in enumerate(feature_available_ats):
                require_aware_datetime(available_at, f"available_at[{index}]")
                if available_at > decision_at:
                    late.append(str(index))
        if late:
            raise LookAheadError(
                "features released after decision_at: " + ", ".join(sorted(late))
            )

    @staticmethod
    def _execution_reasons(price: ExecutablePrice, *, side: str) -> list[str]:
        reasons = list(price.reason_codes)
        if price.trading_status != "ACTIVE":
            reasons.append(f"{side}_{price.trading_status}")
        if not price.has_trade:
            reasons.append(f"{side}_NO_TRADE")
        adverse_limit = (side == "BUY" and price.price_limit_state == "LIMIT_UP") or (
            side == "SELL" and price.price_limit_state == "LIMIT_DOWN"
        )
        if adverse_limit and price.counterparty_volume_confirmed is not True:
            reasons.append(f"{side}_LIMIT_FILL_UNCONFIRMED")
        return reasons


__all__ = [
    "CorporateAction",
    "CorporateActionCoverage",
    "DirectionLabel",
    "ExecutablePrice",
    "LabelDataError",
    "LabelFactory",
    "LabelResult",
    "LabelWindow",
    "LookAheadError",
    "NoTradeBandConfig",
    "TradingCalendar",
    "make_direction_label",
    "make_direction_labels",
    "no_trade_band",
]
