"""Read one immutable TPEX daily-bar revision from private Supabase rows."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from math import isfinite
from typing import Protocol

from .tpex_daily_bar_contracts import (
    TpexDailyBar,
    TpexDailyBarRevision,
    TpexDailyBarSeriesSnapshot,
    daily_bar_revision_hash,
    daily_bar_series_hash,
)


class DailyBarRowSource(Protocol):
    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...


class TpexDailyBarSourceError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} is invalid")
    return value


def _date(value: object) -> date:
    if type(value) is date:
        return value
    return date.fromisoformat(str(value))


def _datetime(value: object) -> datetime:
    parsed = (
        value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("available_at must be timezone-aware")
    return parsed


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("daily-bar numeric field is invalid")
    parsed = float(str(value))
    if not isfinite(parsed):
        raise ValueError("daily-bar numeric field is invalid")
    return parsed


class TpexDailyBarRepository:
    """Freeze the newest complete source revision for each requested trade date."""

    _FIELDS = (
        "daily_bar_id,security_id,trade_date,raw_open,raw_high,raw_low,"
        "raw_close,volume_shares,turnover_ntd,source_id,source_version,available_at"
    )

    def __init__(
        self,
        source: DailyBarRowSource,
        *,
        page_size: int = 500,
        minimum_rows: int = 500,
    ) -> None:
        if not 1 <= page_size <= 1_000 or minimum_rows <= 0:
            raise ValueError("daily-bar repository bounds are invalid")
        self.source = source
        self.page_size = page_size
        self.minimum_rows = minimum_rows

    def fetch_range(
        self,
        *,
        start_date: date,
        as_of_date: date | None = None,
    ) -> TpexDailyBarSeriesSnapshot:
        source_id = self._source_id()
        if as_of_date is not None and as_of_date < start_date:
            raise ValueError("as_of_date precedes the daily delta range")
        rows = self._range_rows(
            source_id=source_id,
            start_date=start_date,
            as_of_date=as_of_date,
        )
        if not rows:
            raise self._error(
                "REVISION_UNAVAILABLE",
                "No TPEX daily-bar revision exists in the requested range",
            )
        grouped: dict[tuple[date, str], list[TpexDailyBar]] = {}
        for row in rows:
            grouped.setdefault((row.trade_date, row.source_version), []).append(row)
        by_date: dict[date, list[tuple[datetime, str, list[TpexDailyBar]]]] = {}
        for (trade_date, source_version), revision_rows in grouped.items():
            by_date.setdefault(trade_date, []).append(
                (
                    max(row.available_at for row in revision_rows),
                    source_version,
                    revision_rows,
                )
            )
        revisions: list[TpexDailyBarRevision] = []
        for trade_date, candidates in sorted(by_date.items()):
            _, source_version, revision_rows = max(
                candidates,
                key=lambda candidate: (candidate[0], candidate[1]),
            )
            if len(revision_rows) < self.minimum_rows:
                raise self._error(
                    "CROSS_SECTION_INCOMPLETE",
                    "A TPEX daily-bar revision is below the completeness floor",
                )
            ordered = tuple(sorted(revision_rows, key=lambda row: row.security_id))
            revisions.append(
                TpexDailyBarRevision(
                    as_of_date=trade_date,
                    source_id=source_id,
                    source_version=source_version,
                    rows=ordered,
                    snapshot_sha256=daily_bar_revision_hash(
                        as_of_date=trade_date,
                        source_id=source_id,
                        source_version=source_version,
                        rows=ordered,
                    ),
                )
            )
        if as_of_date is not None and revisions[-1].as_of_date != as_of_date:
            raise self._error(
                "AS_OF_DATE_UNAVAILABLE",
                "The exact requested TPEX source date is unavailable",
            )
        frozen = tuple(revisions)
        return TpexDailyBarSeriesSnapshot(
            revisions=frozen,
            snapshot_sha256=daily_bar_series_hash(frozen),
        )

    def _source_id(self) -> int:
        rows = self.source.select_rows(
            "data_sources",
            select="source_id,source_code",
            filters={"source_code": "eq.TPEX"},
            limit=2,
        )
        if len(rows) != 1 or rows[0].get("source_code") != "TPEX":
            raise self._error(
                "SOURCE_ID_UNAVAILABLE",
                "Exactly one TPEX data source is required",
            )
        try:
            return _positive_integer(rows[0].get("source_id"), "source_id")
        except ValueError as error:
            raise self._error("SOURCE_ID_INVALID", str(error)) from error

    def _range_rows(
        self,
        *,
        source_id: int,
        start_date: date,
        as_of_date: date | None,
    ) -> list[TpexDailyBar]:
        high_water = self._high_water(source_id=source_id, start_date=start_date)
        if high_water is None:
            return []
        output: list[TpexDailyBar] = []
        last_id = 0
        reached_high_water = False
        while True:
            filters = {
                "source_id": f"eq.{source_id}",
                "trade_date": f"gte.{start_date.isoformat()}",
                "daily_bar_id": f"gt.{last_id}",
                "order": "daily_bar_id.asc",
            }
            page = self.source.select_rows(
                "daily_bars",
                select=self._FIELDS,
                filters=filters,
                limit=self.page_size,
            )
            if len(page) > self.page_size:
                raise self._error("PAGE_INVALID", "TPEX daily-bar page is oversized")
            if not page:
                break
            for raw in page:
                try:
                    daily_bar_id = _positive_integer(
                        raw.get("daily_bar_id"), "daily_bar_id"
                    )
                    if daily_bar_id > high_water:
                        reached_high_water = True
                        break
                    row = TpexDailyBar(
                        daily_bar_id=daily_bar_id,
                        security_id=_positive_integer(
                            raw.get("security_id"), "security_id"
                        ),
                        trade_date=_date(raw.get("trade_date")),
                        open_price=_optional_number(raw.get("raw_open")),
                        high_price=_optional_number(raw.get("raw_high")),
                        low_price=_optional_number(raw.get("raw_low")),
                        close_price=_optional_number(raw.get("raw_close")),
                        trading_volume=_optional_number(raw.get("volume_shares")),
                        trading_value=_optional_number(raw.get("turnover_ntd")),
                        source_id=_positive_integer(raw.get("source_id"), "source_id"),
                        source_version=str(raw.get("source_version") or "").strip(),
                        available_at=_datetime(raw.get("available_at")),
                    )
                except (TypeError, ValueError) as error:
                    raise self._error(
                        "ROW_INVALID", "A TPEX daily-bar row is invalid"
                    ) from error
                if row.daily_bar_id <= last_id:
                    raise self._error(
                        "ORDER_INVALID", "TPEX daily bars are not strictly ordered"
                    )
                last_id = row.daily_bar_id
                if as_of_date is None or row.trade_date <= as_of_date:
                    output.append(row)
            if reached_high_water or last_id >= high_water:
                break
            if len(page) < self.page_size:
                raise self._error(
                    "HIGH_WATER_UNREACHABLE",
                    "TPEX daily-bar rows changed while the snapshot was read",
                )
        if last_id != high_water:
            raise self._error(
                "HIGH_WATER_UNREACHABLE",
                "TPEX daily-bar snapshot did not reach its frozen high water",
            )
        identities = {
            (row.trade_date, row.source_version, row.security_id) for row in output
        }
        if len(identities) != len(output):
            raise self._error(
                "SECURITY_DUPLICATE", "One revision duplicates a security"
            )
        return output

    def _high_water(self, *, source_id: int, start_date: date) -> int | None:
        rows = self.source.select_rows(
            "daily_bars",
            select="daily_bar_id",
            filters={
                "source_id": f"eq.{source_id}",
                "trade_date": f"gte.{start_date.isoformat()}",
                "order": "daily_bar_id.desc",
            },
            limit=1,
        )
        if len(rows) > 1:
            raise self._error("PAGE_INVALID", "TPEX daily-bar high water is invalid")
        if not rows:
            return None
        try:
            return _positive_integer(rows[0].get("daily_bar_id"), "daily_bar_id")
        except ValueError as error:
            raise self._error("HIGH_WATER_INVALID", str(error)) from error

    @staticmethod
    def _error(suffix: str, message: str) -> TpexDailyBarSourceError:
        return TpexDailyBarSourceError(f"TPEX_DAILY_BAR_{suffix}", message)


__all__ = [
    "DailyBarRowSource",
    "TpexDailyBarRepository",
    "TpexDailyBarSourceError",
]
