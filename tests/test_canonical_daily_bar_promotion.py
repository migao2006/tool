from __future__ import annotations

from datetime import date, datetime, timezone
from dataclasses import replace
from hashlib import sha256

import pytest

from src.data.archive.contracts import (
    HistoricalArchiveManifest,
    VerifiedHistoricalArchive,
)
from src.data.canonical import (
    CANONICAL_DAILY_BAR_SCHEMA_VERSION,
    CanonicalDailyBarPromotionService,
    HistoricalDecisionContext,
    HistoricalSecurityResolver,
    ListingPeriodIdentity,
)
from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_SCHEMA_VERSION,
)


TRADE_DATE = date(2024, 1, 2)
DECISION_AT = datetime(2024, 1, 2, 6, 30, tzinfo=timezone.utc)
OBSERVED_AT = datetime(2026, 7, 19, 1, tzinfo=timezone.utc)
BUCKET = "alpha-lens-archive"
OBJECT_KEY = "historical/provider=finmind/symbol=2330/archive.parquet"
ARCHIVE_KEY = sha256(f"{BUCKET}\0{OBJECT_KEY}".encode()).hexdigest()


def _identity() -> ListingPeriodIdentity:
    return ListingPeriodIdentity(
        listing_period_id="listing-2330",
        security_id=2330,
        isin="TW0002330008",
        market="TWSE",
        source_symbol="2330",
        asset_type="COMMON_STOCK",
        effective_from=date(1962, 2, 9),
        effective_to=None,
        available_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        first_observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        source_id=1,
        source_dataset="listing_history",
        source_version="v1",
        source_revision_hash="a" * 64,
        source_payload_hash="b" * 64,
        resolution_status="VERIFIED",
        available_at_basis="VERSIONED_SNAPSHOT",
        point_in_time_status="VERIFIED",
        usage_scope="POINT_IN_TIME_IDENTITY",
        system_status="PASS",
        reason_codes=(),
    )


def _manifest(*, row_count: int = 1) -> HistoricalArchiveManifest:
    return HistoricalArchiveManifest(
        archive_key=ARCHIVE_KEY,
        storage_provider="CLOUDFLARE_R2",
        bucket_name=BUCKET,
        object_key=OBJECT_KEY,
        object_etag="etag",
        schema_version=HISTORICAL_ARCHIVE_SCHEMA_VERSION,
        provider_code="FINMIND",
        source_dataset="daily_bars",
        source_version="api.v4",
        source_symbol="2330",
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        requested_start_date=TRADE_DATE,
        requested_end_date=TRADE_DATE,
        min_trade_date=TRADE_DATE,
        max_trade_date=TRADE_DATE,
        source_payload_hash="c" * 64,
        parquet_sha256="d" * 64,
        byte_size=128,
        row_count=row_count,
        parsed_row_count=row_count,
        quarantined_row_count=0,
        first_observed_at=OBSERVED_AT,
        point_in_time_status="UNVERIFIED",
        usage_scope="RAW_LANDING_ONLY",
        system_status="RESEARCH_ONLY",
        reason_codes=("POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"),
    )


def _row(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "source_symbol": "2330",
        "trade_date": TRADE_DATE,
        "parse_status": "PARSED",
        "open_price": "100",
        "high_price": "103",
        "low_price": "99",
        "close_price": "102",
        "trading_volume": "1000000",
        "trading_value": "101000000",
        "trade_count": 1234,
        "source_revision_hash": "e" * 64,
        "source_payload_hash": "c" * 64,
        "first_observed_at": OBSERVED_AT,
        "available_at": OBSERVED_AT,
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "point_in_time_status": "UNVERIFIED",
    }
    values.update(overrides)
    return values


def _context(
    *,
    calendar_status: str = "VERIFIED",
    calendar_revision_hash: str | None = "f" * 64,
    company_action_coverage_status: str = "VERIFIED",
    company_action_revision_hash: str | None = "1" * 64,
) -> HistoricalDecisionContext:
    return HistoricalDecisionContext(
        market="TWSE",
        trade_date=TRADE_DATE,
        decision_at=DECISION_AT,
        publication_rule_version="twse.close.v1",
        calendar_revision_hash=calendar_revision_hash,
        calendar_available_at=(
            datetime(2024, 1, 1, tzinfo=timezone.utc)
            if calendar_status == "VERIFIED"
            else None
        ),
        calendar_status=calendar_status,
        company_action_coverage_status=company_action_coverage_status,
        company_action_revision_hash=company_action_revision_hash,
        company_action_available_at=(
            datetime(2024, 1, 1, tzinfo=timezone.utc)
            if company_action_coverage_status == "VERIFIED"
            else None
        ),
    )


def _archive(row: dict[str, object]) -> VerifiedHistoricalArchive:
    manifest = _manifest()
    return VerifiedHistoricalArchive(
        manifest=manifest,
        rows=(row,),
        content_sha256=manifest.parquet_sha256,
        byte_size=manifest.byte_size,
        row_count=manifest.row_count,
        schema_version=manifest.schema_version,
    )


def test_raw_archive_can_only_promote_to_traceable_research_row() -> None:
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)),
        {("TWSE", TRADE_DATE): _context()},
    )

    result = service.promote(_archive(_row()))

    assert result.source_row_count == 1
    assert result.rejected_row_count == 0
    assert result.production_eligible_count == 0
    canonical = result.canonical_rows[0]
    assert canonical.schema_version == CANONICAL_DAILY_BAR_SCHEMA_VERSION
    assert canonical.listing_period_id == "listing-2330"
    assert canonical.raw_archive_key == ARCHIVE_KEY
    assert canonical.raw_first_observed_at == OBSERVED_AT
    assert canonical.raw_available_at == OBSERVED_AT
    assert canonical.raw_available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL"
    assert canonical.system_status == "RESEARCH_ONLY"
    assert "RAW_POINT_IN_TIME_UNVERIFIED" in canonical.reason_codes
    assert "BAR_AVAILABLE_AFTER_DECISION" in canonical.reason_codes


def test_promotion_hash_is_deterministic() -> None:
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)),
        {("TWSE", TRADE_DATE): _context()},
    )

    first = service.promote(_archive(_row())).canonical_rows[0]
    second = service.promote(_archive(_row())).canonical_rows[0]

    assert first.canonical_row_hash == second.canonical_row_hash


def test_missing_decision_context_rejects_without_inventing_a_cutoff() -> None:
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)), {}
    )

    result = service.promote(_archive(_row()))

    assert result.canonical_rows == ()
    assert result.rejected_row_count == 1
    assert result.reason_counts == (("DECISION_CONTEXT_UNAVAILABLE", 1),)


def test_unresolved_or_cross_market_identity_is_not_canonicalized() -> None:
    identity = _identity()
    tpex_identity = replace(identity, listing_period_id="tpex", market="TPEX")
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((identity, tpex_identity)),
        {("TWSE", TRADE_DATE): _context()},
    )

    result = service.promote(_archive(_row()))

    assert result.canonical_rows == ()
    assert result.reason_counts == (("HISTORICAL_IDENTITY_AMBIGUOUS", 1),)


def test_unverified_calendar_and_company_actions_remain_visible() -> None:
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)),
        {
            ("TWSE", TRADE_DATE): _context(
                calendar_status="UNVERIFIED",
                calendar_revision_hash=None,
                company_action_coverage_status="UNVERIFIED",
                company_action_revision_hash=None,
            )
        },
    )

    canonical = service.promote(_archive(_row())).canonical_rows[0]

    assert "TRADING_CALENDAR_UNVERIFIED" in canonical.reason_codes
    assert "COMPANY_ACTION_COVERAGE_UNVERIFIED" in canonical.reason_codes
    assert canonical.production_eligible is False


def test_raw_values_and_available_at_are_not_backdated_or_mutated() -> None:
    raw = _row(open_price="101.2500")
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)),
        {("TWSE", TRADE_DATE): _context()},
    )

    canonical = service.promote(_archive(raw)).canonical_rows[0]

    assert str(canonical.open_price) == "101.2500"
    assert canonical.raw_available_at == OBSERVED_AT
    assert raw["available_at"] == OBSERVED_AT


def test_internally_inconsistent_verified_archive_fails_closed() -> None:
    archive = replace(_archive(_row()), row_count=2)
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)),
        {("TWSE", TRADE_DATE): _context()},
    )

    with pytest.raises(ValueError, match="internally inconsistent"):
        _ = service.promote(archive)


def test_canonical_contract_rejects_future_data_and_invalid_prices() -> None:
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)),
        {("TWSE", TRADE_DATE): _context()},
    )
    canonical = service.promote(_archive(_row())).canonical_rows[0]
    future = datetime(2030, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="production-eligible"):
        _ = replace(
            canonical,
            raw_available_at=future,
            raw_first_observed_at=future,
            raw_available_at_basis="VERSIONED_SNAPSHOT",
            point_in_time_status="VERIFIED",
            usage_scope="MODEL_ELIGIBLE",
            system_status="PASS",
            production_eligible=True,
            reason_codes=(),
        )
    with pytest.raises(ValueError, match="prices must be positive"):
        _ = replace(canonical, open_price=-canonical.open_price)


def test_context_mapping_key_cannot_override_context_identity() -> None:
    wrong_context = replace(
        _context(),
        market="TPEX",
        trade_date=date(2024, 1, 3),
        decision_at=datetime(2024, 1, 3, 6, 30, tzinfo=timezone.utc),
    )
    service = CanonicalDailyBarPromotionService(
        HistoricalSecurityResolver((_identity(),)),
        {("TWSE", TRADE_DATE): wrong_context},
    )

    result = service.promote(_archive(_row()))

    assert result.canonical_rows == ()
    assert result.reason_counts == (("DECISION_CONTEXT_IDENTITY_MISMATCH", 1),)
