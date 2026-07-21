"""Canonical label-generation contract."""

from .label_factory import (
    CorporateAction,
    CorporateActionCoverage,
    DirectionLabel,
    ExecutablePrice,
    LabelDataError,
    LabelFactory,
    LabelResult,
    LabelWindow,
    LookAheadError,
    NoTradeBandConfig,
    TradingCalendar,
    make_direction_label,
    make_direction_labels,
    no_trade_band,
)

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
