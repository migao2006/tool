"""Single source of truth for executable forward-return labels.

Signals are made after all allowed data for session ``t`` are available, enter at
the next exchange session's executable open and exit at the close of the ``h``-th
held exchange session. The production model currently permits only ``h=5``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby
from typing import Iterable, Mapping, Sequence

from src.core.horizon import (
    PRODUCTION_HORIZON,
    require_production_horizon,
    require_supported_horizon,
)


ZERO = Decimal("0")
ONE = Decimal("1")


def _decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class LookAheadError(ValueError):
    """Raised when a requested label can see data released after the decision."""


@dataclass(frozen=True)
class LabelWindow:
    decision_date: date
    entry_date: date
    exit_date: date
    horizon: int


class TradingCalendar:
    """Immutable ordered exchange-session calendar."""

    def __init__(self, sessions: Sequence[date]) -> None:
        normalized = tuple(sessions)
        if not normalized:
            raise ValueError("trading calendar cannot be empty")
        if tuple(sorted(set(normalized))) != normalized:
            raise ValueError("trading sessions must be unique and strictly increasing")
        self._sessions = normalized
        self._positions = {session: position for position, session in enumerate(normalized)}

    @property
    def sessions(self) -> tuple[date, ...]:
        return self._sessions

    def label_window(
        self,
        decision_date: date,
        *,
        horizon: int = PRODUCTION_HORIZON,
        research: bool = False,
    ) -> LabelWindow:
        horizon = (
            require_supported_horizon(horizon)
            if research
            else require_production_horizon(horizon)
        )
        try:
            decision_position = self._positions[decision_date]
        except KeyError as exc:
            raise ValueError("decision_date must be an exchange session") from exc
        entry_position = decision_position + 1
        exit_position = decision_position + horizon
        if exit_position >= len(self._sessions):
            raise ValueError("calendar does not contain the complete label window")
        return LabelWindow(
            decision_date=decision_date,
            entry_date=self._sessions[entry_position],
            exit_date=self._sessions[exit_position],
            horizon=horizon,
        )


@dataclass(frozen=True)
class ExecutablePrice:
    session_date: date
    price: Decimal
    has_trade: bool = True
    trading_status: str = "ACTIVE"
    price_limit_state: str = "NONE"
    counterparty_volume_confirmed: bool | None = None
    price_basis: str = "UNADJUSTED"
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", _decimal(self.price))
        if self.price <= ZERO:
            raise ValueError("executable price must be positive")
        valid_statuses = {"ACTIVE", "SUSPENDED", "STOPPED", "DELISTED"}
        if self.trading_status not in valid_statuses:
            raise ValueError(f"unknown trading_status: {self.trading_status}")
        if self.price_limit_state not in {"NONE", "LIMIT_UP", "LIMIT_DOWN"}:
            raise ValueError(f"unknown price_limit_state: {self.price_limit_state}")
        if self.price_basis != "UNADJUSTED":
            raise ValueError("execution simulation requires unadjusted market prices")


@dataclass(frozen=True)
class CorporateAction:
    """An ex-date entitlement expressed per pre-action share.

    A position bought at the open on ``ex_date`` is too late to receive the
    entitlement. A position already held before ``ex_date`` keeps a cash-dividend
    receivable even when ``payable_date`` falls after the modeled exit. This maps
    directly to the point-in-time corporate-action ``ex_date``/``payable_date``
    storage contract and avoids using adjusted prices as executable prices.
    """

    action_id: str
    ex_date: date
    payable_date: date | None = None
    cash_per_share: Decimal = ZERO
    share_multiplier: Decimal = ONE
    source_available_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash_per_share", _decimal(self.cash_per_share))
        object.__setattr__(self, "share_multiplier", _decimal(self.share_multiplier))
        if self.cash_per_share < ZERO or self.share_multiplier <= ZERO:
            raise ValueError("corporate-action cash cannot be negative and multiplier must be positive")
        if self.payable_date is not None and self.payable_date < self.ex_date:
            raise ValueError("payable_date cannot precede ex_date")
        if self.source_available_at is not None:
            _require_aware(self.source_available_at, "source_available_at")


@dataclass(frozen=True)
class LabelResult:
    symbol: str
    window: LabelWindow
    valid: bool
    gross_return: Decimal | None
    net_return: Decimal | None
    benchmark_return: Decimal | None
    excess_return: Decimal | None
    round_trip_cost_rate: Decimal
    benchmark_id: str
    benchmark_version: str
    reason_codes: tuple[str, ...]
    applied_corporate_actions: tuple[str, ...]


class LabelFactory:
    """Build labels used by ranking, direction and return-distribution models."""

    def __init__(self, calendar: TradingCalendar) -> None:
        self.calendar = calendar

    def create(
        self,
        *,
        symbol: str,
        decision_at: datetime,
        entry_open: ExecutablePrice,
        exit_close: ExecutablePrice,
        benchmark_return: Decimal | int | float | str,
        benchmark_id: str,
        benchmark_version: str,
        round_trip_cost_rate: Decimal | int | float | str,
        feature_available_ats: Mapping[str, datetime] | Iterable[datetime] = (),
        corporate_actions: Iterable[CorporateAction] = (),
        horizon: int = PRODUCTION_HORIZON,
        research: bool = False,
    ) -> LabelResult:
        _require_aware(decision_at, "decision_at")
        self._audit_available_at(feature_available_ats, decision_at)
        window = self.calendar.label_window(
            decision_at.date(), horizon=horizon, research=research
        )
        if entry_open.session_date != window.entry_date:
            raise ValueError("entry price must be the t+1 exchange-session open")
        if exit_close.session_date != window.exit_date:
            raise ValueError("exit price must be the h-th held exchange-session close")

        cost_rate = _decimal(round_trip_cost_rate)
        benchmark = _decimal(benchmark_return)
        if cost_rate < ZERO:
            raise ValueError("round-trip cost rate cannot be negative")
        if not benchmark_id or not benchmark_version:
            raise ValueError("benchmark id and version are required for model metadata")

        execution_reasons = self._execution_reasons(entry_open, side="BUY")
        execution_reasons.extend(self._execution_reasons(exit_close, side="SELL"))
        if execution_reasons:
            return LabelResult(
                symbol=symbol,
                window=window,
                valid=False,
                gross_return=None,
                net_return=None,
                benchmark_return=None,
                excess_return=None,
                round_trip_cost_rate=cost_rate,
                benchmark_id=benchmark_id,
                benchmark_version=benchmark_version,
                reason_codes=tuple(dict.fromkeys(execution_reasons)),
                applied_corporate_actions=(),
            )

        shares = ONE
        cash = ZERO
        applied: list[str] = []
        entitled_actions = sorted(
            (
                action
                for action in corporate_actions
                if window.entry_date < action.ex_date <= window.exit_date
            ),
            key=lambda action: action.ex_date,
        )
        # Realized actions define the future target cash flow. They are deliberately
        # separate from feature_available_ats and cannot enter decision features.
        # Buying at the ex-date open is not entitled. Once entitled, a later
        # payable date does not erase the dividend receivable from total return.
        # Cash and share entitlements on one ex-date are both based on pre-action
        # shares, so their result cannot depend on input record ordering.
        for _, same_date_actions in groupby(
            entitled_actions,
            key=lambda action: action.ex_date,
        ):
            actions = tuple(same_date_actions)
            pre_action_shares = shares
            cash += pre_action_shares * sum(
                (action.cash_per_share for action in actions),
                start=ZERO,
            )
            for action in actions:
                shares *= action.share_multiplier
                applied.append(action.action_id)

        terminal_value = shares * exit_close.price + cash
        gross_return = terminal_value / entry_open.price - ONE
        net_return = gross_return - cost_rate
        excess_return = net_return - benchmark
        return LabelResult(
            symbol=symbol,
            window=window,
            valid=True,
            gross_return=gross_return,
            net_return=net_return,
            benchmark_return=benchmark,
            excess_return=excess_return,
            round_trip_cost_rate=cost_rate,
            benchmark_id=benchmark_id,
            benchmark_version=benchmark_version,
            reason_codes=(),
            applied_corporate_actions=tuple(applied),
        )

    @staticmethod
    def _audit_available_at(
        feature_available_ats: Mapping[str, datetime] | Iterable[datetime],
        decision_at: datetime,
    ) -> None:
        values = (
            feature_available_ats.items()
            if isinstance(feature_available_ats, Mapping)
            else enumerate(feature_available_ats)
        )
        late: list[str] = []
        for name, available_at in values:
            _require_aware(available_at, f"available_at[{name}]")
            if available_at > decision_at:
                late.append(str(name))
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
        adverse_limit = (
            side == "BUY" and price.price_limit_state == "LIMIT_UP"
        ) or (side == "SELL" and price.price_limit_state == "LIMIT_DOWN")
        if adverse_limit and price.counterparty_volume_confirmed is not True:
            reasons.append(f"{side}_LIMIT_FILL_UNCONFIRMED")
        return reasons
