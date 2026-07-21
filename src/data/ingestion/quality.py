"""Hard gates applied before the first production database write."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from .contracts import IngestionError


MIN_SECURITIES_PER_MARKET = 500
MIN_BAR_COVERAGE = 0.90
MAX_SOURCE_AGE_DAYS = 14


@dataclass(frozen=True)
class FirstStageQuality:
    source_date: date
    source_dates: Mapping[str, str]


def _single_date(rows: Sequence[Mapping[str, object]], market: str) -> date:
    values = {str(row.get("trade_date") or "") for row in rows}
    values.discard("")
    if len(values) != 1:
        raise IngestionError(
            "SOURCE_DATE_INCONSISTENT",
            f"{market} daily bars must contain exactly one source date",
        )
    return date.fromisoformat(next(iter(values)))


def validate_first_stage_batch(
    *,
    requested_as_of_date: date,
    listed_securities: Sequence[Mapping[str, object]],
    otc_securities: Sequence[Mapping[str, object]],
    twse_bars: Sequence[Mapping[str, object]],
    tpex_bars: Sequence[Mapping[str, object]],
) -> FirstStageQuality:
    market_inputs = (
        ("TWSE", listed_securities, twse_bars),
        ("TPEX", otc_securities, tpex_bars),
    )
    dates: dict[str, date] = {}
    for market, securities, bars in market_inputs:
        if len(securities) < MIN_SECURITIES_PER_MARKET:
            raise IngestionError(
                "SECURITY_MASTER_COVERAGE_TOO_LOW",
                f"{market} security master is below the minimum coverage",
            )
        coverage = len(bars) / len(securities)
        if coverage < MIN_BAR_COVERAGE:
            raise IngestionError(
                "DAILY_BAR_COVERAGE_TOO_LOW",
                f"{market} daily-bar coverage is below the required threshold",
            )
        dates[market] = _single_date(bars, market)

    if dates["TWSE"] != dates["TPEX"]:
        raise IngestionError(
            "SOURCE_MARKET_DATE_MISMATCH",
            "TWSE and TPEX daily bars are not aligned to the same trading date",
            context={
                "requested_as_of_date": requested_as_of_date.isoformat(),
                "twse_source_date": dates["TWSE"].isoformat(),
                "tpex_source_date": dates["TPEX"].isoformat(),
            },
        )
    source_date = dates["TWSE"]
    if source_date > requested_as_of_date:
        raise IngestionError(
            "SOURCE_DATA_FROM_FUTURE",
            "source trading date is later than the requested as-of date",
        )
    if (requested_as_of_date - source_date).days > MAX_SOURCE_AGE_DAYS:
        raise IngestionError(
            "SOURCE_DATA_STALE",
            "source trading date is too old for a current daily import",
        )
    return FirstStageQuality(
        source_date=source_date,
        source_dates={market: value.isoformat() for market, value in dates.items()},
    )
