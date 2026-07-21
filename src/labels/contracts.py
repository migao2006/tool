"""Immutable inputs and outputs for executable forward-return labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .direction_label import DirectionLabel


ZERO = Decimal("0")
ONE = Decimal("1")


class LookAheadError(ValueError):
    """Raised when a requested label can see data released after the decision."""


class LabelDataError(ValueError):
    """Raised when required point-in-time label inputs are missing or unverified."""


def decimal_label_value(
    value: Decimal | int | float | str,
    *,
    name: str = "value",
) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LabelDataError(f"{name} must be a finite number") from exc
    if not result.is_finite():
        raise LabelDataError(f"{name} must be a finite number")
    return result


def require_aware_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class LabelWindow:
    decision_date: date
    entry_date: date
    exit_date: date
    horizon: int


@dataclass(frozen=True)
class ExecutablePrice:
    session_date: date
    price: Decimal | int | float | str | None
    has_trade: bool = True
    trading_status: str = "ACTIVE"
    price_limit_state: str = "NONE"
    counterparty_volume_confirmed: bool | None = None
    price_basis: str = "UNADJUSTED"
    bid: Decimal | int | float | str | None = None
    ask: Decimal | int | float | str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        raw_price = self.price
        if raw_price is None:
            raise LabelDataError("executable price is required")
        price = decimal_label_value(raw_price, name="price")
        object.__setattr__(
            self,
            "price",
            price,
        )
        if price <= ZERO:
            raise ValueError("executable price must be positive")
        if (self.bid is None) != (self.ask is None):
            raise LabelDataError(
                "bid and ask must either both be present or both be absent"
            )
        if self.bid is not None and self.ask is not None:
            bid = decimal_label_value(self.bid, name="bid")
            ask = decimal_label_value(self.ask, name="ask")
            if bid <= ZERO or ask <= ZERO or ask < bid:
                raise ValueError("quotes must be positive and ask cannot be below bid")
            object.__setattr__(self, "bid", bid)
            object.__setattr__(self, "ask", ask)
        valid_statuses = {"ACTIVE", "SUSPENDED", "STOPPED", "DELISTED"}
        if self.trading_status not in valid_statuses:
            raise ValueError(f"unknown trading_status: {self.trading_status}")
        if self.price_limit_state not in {"NONE", "LIMIT_UP", "LIMIT_DOWN"}:
            raise ValueError(f"unknown price_limit_state: {self.price_limit_state}")
        if self.price_basis != "UNADJUSTED":
            raise ValueError("execution simulation requires unadjusted market prices")

    @property
    def decimal_price(self) -> Decimal:
        """Return the normalized positive price established by ``__post_init__``."""

        if not isinstance(self.price, Decimal):  # pragma: no cover - invariant guard
            raise LabelDataError("executable price was not normalized")
        return self.price


@dataclass(frozen=True)
class CorporateAction:
    """An ex-date cash/share entitlement expressed per pre-action share."""

    action_id: str
    ex_date: date
    payable_date: date | None = None
    cash_per_share: Decimal = ZERO
    share_multiplier: Decimal = ONE
    source_available_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.action_id:
            raise LabelDataError("corporate-action id is required")
        object.__setattr__(
            self,
            "cash_per_share",
            decimal_label_value(self.cash_per_share, name="cash_per_share"),
        )
        object.__setattr__(
            self,
            "share_multiplier",
            decimal_label_value(self.share_multiplier, name="share_multiplier"),
        )
        if self.cash_per_share < ZERO or self.share_multiplier <= ZERO:
            raise ValueError(
                "corporate-action cash cannot be negative and multiplier must be positive"
            )
        if self.payable_date is not None and self.payable_date < self.ex_date:
            raise ValueError("payable_date cannot precede ex_date")
        if self.source_available_at is not None:
            require_aware_datetime(self.source_available_at, "source_available_at")


@dataclass(frozen=True)
class CorporateActionCoverage:
    """Evidence that the complete action window was checked, including no actions."""

    start_date: date
    end_date: date
    source_version: str
    complete: bool = True

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("corporate-action coverage end cannot precede start")
        if not self.source_version:
            raise LabelDataError("corporate-action source version is required")

    def covers(self, window: LabelWindow) -> bool:
        return (
            self.complete
            and self.start_date <= window.entry_date
            and self.end_date >= window.exit_date
        )


@dataclass(frozen=True)
class LabelResult:
    symbol: str
    window: LabelWindow
    valid: bool
    gross_return: Decimal | None
    net_return: Decimal | None
    benchmark_return: Decimal | None
    excess_return: Decimal | None
    round_trip_cost_rate: Decimal | None
    cost_profile_version: str | None
    benchmark_id: str
    benchmark_version: str
    direction: DirectionLabel | None
    no_trade_band: Decimal | None
    no_trade_band_version: str | None
    reason_codes: tuple[str, ...]
    applied_corporate_actions: tuple[str, ...]

    @property
    def benchmark_alpha(self) -> Decimal | None:
        """Net stock return minus the versioned corresponding benchmark return."""

        return self.excess_return


__all__ = [
    "CorporateAction",
    "CorporateActionCoverage",
    "ExecutablePrice",
    "LabelDataError",
    "LabelResult",
    "LabelWindow",
    "LookAheadError",
]
