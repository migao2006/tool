from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import cast
from uuid import UUID

from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.archive.historical_parquet_validation import validate_historical_parquet
from src.data.ingestion.historical_backfill_contracts import HistoricalBackfillTask
from src.data.ingestion.historical_benchmark_contracts import (
    BENCHMARK_DATASET,
    BENCHMARK_DATA_ID,
    HistoricalBenchmarkBackfillState,
    HistoricalBenchmarkLandingResult,
)
from src.data.ingestion.historical_benchmark_coordinator import (
    HistoricalBenchmarkBackfillCoordinator,
)
from src.data.ingestion.historical_benchmark_landing_service import (
    HistoricalBenchmarkLandingService,
)
from src.data.ingestion.historical_benchmark_normalizer import (
    normalize_historical_benchmark,
)
from src.data.ingestion.historical_benchmark_parquet import (
    serialize_historical_benchmark_parquet,
)
from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_daily_bar_archive_service import (
    HistoricalArchiveWriteResult,
)
from src.data.providers.contracts import ProviderPayload


START = date(2021, 7, 19)
END = date(2026, 7, 17)
RETRIEVED_AT = datetime(2026, 7, 19, 5, tzinfo=timezone.utc)


def _payload(rows: Sequence[object]) -> ProviderPayload:
    body = {"status": 200, "data": list(rows)}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset=BENCHMARK_DATASET,
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=RETRIEVED_AT,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


class FakeProvider:
    def __init__(self, payload: ProviderPayload) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str | None, object, object]] = []

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        self.calls.append((dataset, data_id, start_date, end_date))
        return self.payload


class FakeArchive:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def archive(
        self,
        *,
        rows: Sequence[Mapping[str, object]],
        quarantine_rows: Sequence[Mapping[str, object]],
        payload: ProviderPayload,
        scheduled_market: str,
        asset_type: str,
        symbol: str,
        start_date: date,
        end_date: date,
        backfill_task_id: int | None,
    ) -> HistoricalArchiveWriteResult:
        self.calls.append(
            {
                "rows": rows,
                "quarantine_rows": quarantine_rows,
                "payload": payload,
                "scheduled_market": scheduled_market,
                "asset_type": asset_type,
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "backfill_task_id": backfill_task_id,
            }
        )
        return HistoricalArchiveWriteResult(
            "raw/v1/benchmark.parquet",
            True,
            "a" * 64,
            100,
            len(rows),
        )


def test_normalizer_preserves_rows_and_quarantines_invalid_values() -> None:
    batch = normalize_historical_benchmark(
        _payload(
            [
                {"date": "2021-07-19", "stock_id": "TAIEX", "price": 30123.4},
                {"date": "bad", "stock_id": "OTHER", "price": -1},
            ]
        )
    )

    assert batch.source_row_count == 2
    assert batch.parsed_count == 1
    assert batch.quarantined_count == 1
    parsed = batch.landing_rows[0]
    assert parsed["point_in_time_status"] == "UNVERIFIED"
    assert parsed["usage_scope"] == "RAW_LANDING_ONLY"
    assert parsed["system_status"] == "RESEARCH_ONLY"
    assert parsed["available_at"] == RETRIEVED_AT.isoformat()
    assert parsed["source_row"] == {
        "date": "2021-07-19",
        "stock_id": "TAIEX",
        "price": 30123.4,
    }
    assert {row["reason_code"] for row in batch.quarantine_rows} == {
        "BENCHMARK_DATA_ID_MISMATCH",
        "OBSERVATION_DATE_INVALID",
        "BENCHMARK_PRICE_INVALID",
    }


def test_parquet_is_zstd_and_keeps_research_metadata() -> None:
    payload = _payload([{"date": "2021-07-19", "stock_id": "TAIEX", "price": 30123.4}])
    batch = normalize_historical_benchmark(payload)
    request = HistoricalArchiveRequest(
        scheduled_market="TWSE",
        asset_type="BENCHMARK",
        source_symbol="TAIEX",
        requested_start_date=START,
        requested_end_date=END,
        source_payload_sha256=payload.payload_sha256,
        retrieved_at=payload.retrieved_at,
        source_dataset=BENCHMARK_DATASET,
    )

    artifact = serialize_historical_benchmark_parquet(
        batch.landing_rows,
        request=request,
    )

    import pyarrow.parquet as pq

    table = pq.read_table(cast(object, __import__("io").BytesIO(artifact.payload)))
    metadata = table.schema.metadata or {}
    assert artifact.schema_version == "historical_benchmark_total_return.v1"
    assert artifact.compression == "ZSTD"
    assert "dataset=benchmark_total_return" in artifact.object_key
    assert "symbol=TAIEX" in artifact.object_key
    assert metadata[b"available_at.semantics"] == b"first-project-retrieval-only"
    assert table.column("price").to_pylist() == [30123.4]

    bucket = "alpha-lens-archive"
    manifest = HistoricalArchiveManifest.from_mapping(
        {
            "archive_key": sha256(
                f"{bucket}\0{artifact.object_key}".encode()
            ).hexdigest(),
            "storage_provider": "CLOUDFLARE_R2",
            "bucket_name": bucket,
            "object_key": artifact.object_key,
            "object_etag": None,
            "schema_version": artifact.schema_version,
            "provider_code": "FINMIND",
            "source_dataset": BENCHMARK_DATASET,
            "source_version": "api.v4",
            "source_symbol": BENCHMARK_DATA_ID,
            "scheduled_market": "TWSE",
            "asset_type": "BENCHMARK",
            "requested_start_date": START,
            "requested_end_date": END,
            "min_trade_date": START,
            "max_trade_date": START,
            "source_payload_hash": payload.payload_sha256,
            "parquet_sha256": artifact.content_sha256,
            "byte_size": artifact.byte_size,
            "row_count": 1,
            "parsed_row_count": 1,
            "quarantined_row_count": 0,
            "first_observed_at": RETRIEVED_AT,
            "point_in_time_status": "UNVERIFIED",
            "usage_scope": "RAW_LANDING_ONLY",
            "system_status": "RESEARCH_ONLY",
            "reason_codes": ["POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"],
        }
    )
    verified = validate_historical_parquet(artifact.payload, manifest)
    assert verified[0]["price"] == 30123.4


def test_landing_uses_exactly_one_fixed_finmind_request() -> None:
    provider = FakeProvider(
        _payload(
            [
                {"date": "2021-07-19", "stock_id": "TAIEX", "price": 30123.4},
                {"date": "2026-07-17", "stock_id": "TAIEX", "price": 50123.4},
            ]
        )
    )
    archive = FakeArchive()

    result = HistoricalBenchmarkLandingService(
        provider=provider,
        archive_service=archive,
    ).land(start_date=START, end_date=END, backfill_task_id=17)

    assert provider.calls == [(BENCHMARK_DATASET, BENCHMARK_DATA_ID, START, END)]
    assert len(archive.calls) == 1
    assert archive.calls[0]["asset_type"] == "BENCHMARK"
    assert archive.calls[0]["scheduled_market"] == "TWSE"
    assert result.fetched_rows == result.archived_rows == 2
    assert result.latest_trade_date == END.isoformat()


class FakeRepository:
    def __init__(
        self,
        task: HistoricalBackfillTask | None,
        *,
        state: HistoricalBenchmarkBackfillState | None = None,
    ) -> None:
        self.task: HistoricalBackfillTask | None = task
        self.state = state or HistoricalBenchmarkBackfillState(
            archive_exists=True,
            task_id=17,
            task_status="SUCCEEDED",
            last_error_code=None,
        )
        self.completed: list[dict[str, object]] = []
        self.ensure_calls: int = 0
        self.seed_calls: int = 0

    def ensure_finmind_source(self) -> None:
        self.ensure_calls += 1

    def seed(
        self,
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int:
        _ = (start_date, end_date, selection_snapshot_at)
        self.seed_calls += 1
        return 1

    def claim(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None:
        _ = (worker_id, claim_token, lease_seconds)
        task, self.task = self.task, None
        return task

    def complete(self, **values: object) -> None:
        self.completed.append(values)

    def backfill_state(
        self, *, start_date: date, end_date: date
    ) -> HistoricalBenchmarkBackfillState:
        _ = (start_date, end_date)
        return self.state


class FakeLanding:
    def __init__(self) -> None:
        self.calls = 0

    def land(
        self,
        *,
        start_date: date,
        end_date: date,
        backfill_task_id: int,
    ) -> HistoricalBenchmarkLandingResult:
        _ = (start_date, end_date, backfill_task_id)
        self.calls += 1
        return HistoricalBenchmarkLandingResult(
            fetched_rows=2,
            archived_rows=2,
            quarantined_rows=0,
            quarantine_issues=0,
            latest_trade_date=END.isoformat(),
            source_payload_hash="a" * 64,
            object_key="raw/v1/benchmark.parquet",
        )


def _task() -> HistoricalBackfillTask:
    return HistoricalBackfillTask(
        task_id=17,
        source_dataset=BENCHMARK_DATASET,
        symbol=BENCHMARK_DATA_ID,
        display_name="TAIEX Total Return Index",
        market="TWSE",
        asset_type="BENCHMARK",
        priority=30,
        start_date=START,
        end_date=END,
        attempt_count=1,
        max_attempts=5,
    )


def test_coordinator_processes_at_most_one_task_and_marks_research_only() -> None:
    repository = FakeRepository(_task())
    landing = FakeLanding()

    summary = HistoricalBenchmarkBackfillCoordinator(
        repository=repository,
        landing_service=landing,
        now_fn=lambda: RETRIEVED_AT,
    ).run(start_date=START, end_date=END, worker_id="benchmark-test")

    assert landing.calls == 1
    assert summary.request_count == 1
    assert summary.system_status == "RESEARCH_ONLY"
    assert summary.usage_scope == "RAW_LANDING_ONLY"
    assert summary.point_in_time_status == "UNVERIFIED"
    assert repository.completed[0]["success"] is True


def test_coordinator_makes_no_provider_request_when_archive_is_complete() -> None:
    repository = FakeRepository(None)
    landing = FakeLanding()

    summary = HistoricalBenchmarkBackfillCoordinator(
        repository=repository,
        landing_service=landing,
        now_fn=lambda: RETRIEVED_AT,
    ).run(start_date=START, end_date=END, worker_id="benchmark-test")

    assert landing.calls == 0
    assert summary.outcome == "ALREADY_ARCHIVED"
    assert summary.request_count == 0
    assert "BENCHMARK_TASK_SUCCEEDED" in summary.reason_codes
