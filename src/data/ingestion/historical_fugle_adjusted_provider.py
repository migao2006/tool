"""Adapt Fugle adjusted candles to the logical adjusted-bars archive dataset."""

from __future__ import annotations

from datetime import date
from typing import Protocol, cast, final

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError


FUGLE_MAX_RANGE_DAYS = 366
FUGLE_ADJUSTED_DATASET = "adjusted_bars"
FUGLE_REMOTE_DATASET = "historical_candles"


class FugleAdjustedClient(Protocol):
    def historical_candles(
        self,
        symbol: str,
        *,
        start_date: date | str,
        end_date: date | str,
        adjusted: bool = False,
    ) -> ProviderPayload: ...


def _required_date(value: date | str | None, *, field: str) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise IngestionError(
                "FUGLE_ADJUSTED_RANGE_INVALID",
                f"{field} must use YYYY-MM-DD",
            ) from error
    raise IngestionError(
        "FUGLE_ADJUSTED_RANGE_INVALID",
        f"{field} is required",
    )


@final
class FugleAdjustedBackfillProvider:
    """Expose only adjusted daily candles through the supplemental interface."""

    def __init__(self, client: FugleAdjustedClient) -> None:
        self._client = client

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        if dataset != FUGLE_ADJUSTED_DATASET:
            raise IngestionError(
                "FUGLE_ADJUSTED_DATASET_INVALID",
                "Fugle backfill adapter accepts adjusted_bars only",
            )
        symbol = (data_id or "").strip()
        if not symbol:
            raise IngestionError(
                "FUGLE_ADJUSTED_SYMBOL_MISSING",
                "Fugle adjusted backfill requires a symbol",
            )
        range_start = _required_date(start_date, field="start_date")
        range_end = _required_date(end_date, field="end_date")
        if range_end < range_start:
            raise IngestionError(
                "FUGLE_ADJUSTED_RANGE_INVALID",
                "start_date must not be after end_date",
            )
        inclusive_days = (range_end - range_start).days + 1
        if inclusive_days > FUGLE_MAX_RANGE_DAYS:
            raise IngestionError(
                "FUGLE_ADJUSTED_RANGE_LIMIT",
                "Fugle adjusted candle requests cannot exceed one year",
            )

        remote = self._client.historical_candles(
            symbol,
            start_date=range_start,
            end_date=range_end,
            adjusted=True,
        )
        if remote.provider != "FUGLE" or remote.dataset != FUGLE_REMOTE_DATASET:
            raise IngestionError(
                "FUGLE_ADJUSTED_SOURCE_INVALID",
                "Fugle returned an unexpected provider or remote dataset",
            )
        if remote.request_metadata.get("adjusted") != "true":
            raise IngestionError(
                "FUGLE_ADJUSTED_PROVENANCE_INVALID",
                "Fugle adjusted archive requires adjusted=true provenance",
            )
        if remote.request_metadata.get("symbol") != symbol:
            raise IngestionError(
                "FUGLE_ADJUSTED_PROVENANCE_INVALID",
                "Fugle adjusted archive symbol provenance does not match",
            )
        return ProviderPayload(
            provider=remote.provider,
            dataset=FUGLE_ADJUSTED_DATASET,
            source_version=remote.source_version,
            source_url=remote.source_url,
            retrieved_at=remote.retrieved_at,
            payload_sha256=remote.payload_sha256,
            payload=cast(object, remote.payload),
            request_metadata={
                **remote.request_metadata,
                "logical_dataset": FUGLE_ADJUSTED_DATASET,
                "remote_dataset": FUGLE_REMOTE_DATASET,
            },
        )
