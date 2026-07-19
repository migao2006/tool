from pathlib import Path
from dataclasses import dataclass
from hashlib import sha256

from src.quality.historical_archive_audit import audit_historical_archive


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/20260719062000_historical_benchmark_archive.sql"


def test_migration_isolates_one_research_only_benchmark_queue() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "'benchmark_total_return'" in sql
    assert "'historical_benchmark_total_return.v1'" in sql
    assert "asset_type = 'BENCHMARK'" in sql
    assert "source_symbol = 'TAIEX'" in sql
    assert "point_in_time_status = 'UNVERIFIED'" in sql
    assert "usage_scope = 'RAW_LANDING_ONLY'" in sql
    assert "system_status = 'RESEARCH_ONLY'" in sql
    assert "seed_historical_benchmark_backfill_task" in sql
    assert "claim_historical_benchmark_backfill_task" in sql
    assert "to service_role" in sql
    assert "from public, anon, authenticated" in sql
    assert "OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY" in sql
    assert "IDENTITY_UNRESOLVED" in sql


def test_migration_does_not_write_current_benchmark_tables() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "insert into market_data.market_observations" not in sql
    assert "insert into market_data.benchmark_definitions" not in sql


@dataclass(frozen=True)
class _Inspection:
    content_sha256: str
    byte_size: int
    row_count: int
    schema_version: str


class _Reader:
    def read(self, manifest: dict[str, object]) -> _Inspection:
        return _Inspection(
            content_sha256=str(manifest["parquet_sha256"]),
            byte_size=int(str(manifest["byte_size"])),
            row_count=int(str(manifest["row_count"])),
            schema_version=str(manifest["schema_version"]),
        )


def test_archive_auditor_accepts_versioned_benchmark_manifest() -> None:
    bucket = "alpha-lens-archive"
    key = "raw/v1/dataset=benchmark_total_return/payload.parquet"
    manifest: dict[str, object] = {
        "archive_key": sha256(f"{bucket}\0{key}".encode()).hexdigest(),
        "bucket_name": bucket,
        "object_key": key,
        "parquet_sha256": "a" * 64,
        "byte_size": 100,
        "row_count": 2,
        "parsed_row_count": 2,
        "quarantined_row_count": 0,
        "schema_version": "historical_benchmark_total_return.v1",
        "source_dataset": "benchmark_total_return",
    }

    result = audit_historical_archive([manifest], reader=_Reader())

    assert result.passed
