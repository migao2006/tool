"""Verified corporate-action cash-flow handling for executable total return."""

from __future__ import annotations

from decimal import Decimal
from itertools import groupby

from .contracts import (
    CorporateAction,
    CorporateActionCoverage,
    LabelDataError,
    LabelWindow,
    ONE,
    ZERO,
)
from .trading_calendar import TradingCalendar


def validate_corporate_action_inputs(
    *,
    calendar: TradingCalendar,
    actions: tuple[CorporateAction, ...],
    coverage: CorporateActionCoverage | None,
    window: LabelWindow,
) -> None:
    if coverage is None:
        raise LabelDataError(
            "corporate_action_coverage is required; an empty action list does not "
            + "prove that no action occurred"
        )
    if not coverage.covers(window):
        raise LabelDataError(
            "corporate-action data does not completely cover the label window"
        )
    action_ids = [action.action_id for action in actions]
    if len(set(action_ids)) != len(action_ids):
        raise LabelDataError("corporate-action ids must be unique")
    invalid_ex_dates = sorted(
        {
            action.ex_date
            for action in actions
            if window.entry_date < action.ex_date <= window.exit_date
            and not calendar.is_session(action.ex_date)
        }
    )
    if invalid_ex_dates:
        raise LabelDataError(
            "corporate-action ex dates are not exchange sessions: "
            + ", ".join(day.isoformat() for day in invalid_ex_dates)
        )


def executable_total_return(
    *,
    entry_price: Decimal,
    exit_price: Decimal,
    actions: tuple[CorporateAction, ...],
    window: LabelWindow,
) -> tuple[Decimal, tuple[str, ...]]:
    """Apply only verified future target cash flows to unadjusted execution prices."""

    shares = ONE
    cash = ZERO
    applied: list[str] = []
    entitled_actions = sorted(
        (
            action
            for action in actions
            if window.entry_date < action.ex_date <= window.exit_date
        ),
        key=lambda action: action.ex_date,
    )
    # Buying at the ex-date open is too late for entitlement. Cash and share
    # entitlements on one ex-date both use pre-action shares, independent of order.
    for _, same_date_actions in groupby(
        entitled_actions,
        key=lambda action: action.ex_date,
    ):
        grouped_actions = tuple(same_date_actions)
        pre_action_shares = shares
        cash += pre_action_shares * sum(
            (action.cash_per_share for action in grouped_actions),
            start=ZERO,
        )
        for action in grouped_actions:
            shares *= action.share_multiplier
            applied.append(action.action_id)

    terminal_value = shares * exit_price + cash
    return terminal_value / entry_price - ONE, tuple(applied)
