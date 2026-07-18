from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.normalizers import (
    normalize_company_profiles,
    normalize_daily_bars,
    revision_version,
)
from src.data.ingestion.roc_date import parse_exchange_date
from src.data.ingestion.quality import validate_first_stage_batch
from src.data.ingestion.supabase_writer import RestResponse, SupabaseWriter
from src.data.providers.contracts import ProviderPayload


def payload(provider: str, dataset: str, rows: list[dict[str, object]]) -> ProviderPayload:
    digest = sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return ProviderPayload(
        provider=provider,
        dataset=dataset,
        source_version="openapi.v1",
        source_url="https://example.test/source",
        retrieved_at=datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc),
        payload_sha256=digest,
        payload=rows,
    )


class FakeRestTransport:
    def __init__(self, responses: list[RestResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, method, url, *, headers, body, timeout):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body, "timeout": timeout}
        )
        return self.responses.pop(0)


def test_roc_and_gregorian_exchange_dates_are_explicit() -> None:
    assert parse_exchange_date("1150717").isoformat() == "2026-07-17"
    assert parse_exchange_date("19620209").isoformat() == "1962-02-09"
    with pytest.raises(IngestionError, match="date"):
        parse_exchange_date("2026-13-40")


def test_company_profiles_only_admit_numeric_four_digit_common_stocks() -> None:
    source = payload(
        "MOPS",
        "listed_company_profile",
        [
            {"公司代號": "2330", "公司簡稱": "台積電", "上市日期": "19940905"},
            {"公司代號": "006208", "公司簡稱": "ETF", "上市日期": "20120622"},
            {"公司代號": "9103", "公司簡稱": "美德醫療-DR", "上市日期": "20021213"},
            {"公司代號": "", "公司簡稱": "缺漏"},
        ],
    )
    rows, excluded = normalize_company_profiles(source, market="TWSE", source_id=7)
    assert excluded == 3
    assert rows == [
        {
            "symbol": "2330",
            "display_name": "台積電",
            "market": "TWSE",
            "asset_type": "COMMON_STOCK",
            "currency": "TWD",
            "listing_date": "1994-09-05",
            "source_id": 7,
        }
    ]


def test_otc_company_profiles_use_the_official_english_key_contract() -> None:
    source = payload(
        "MOPS",
        "otc_company_profile",
        [
            {
                "SecuritiesCompanyCode": "1240",
                "CompanyName": "茂生農經股份有限公司",
                "CompanyAbbreviation": "茂生農經",
                "DateOfListing": "20180808",
            }
        ],
    )
    rows, excluded = normalize_company_profiles(source, market="TPEX", source_id=9)
    assert excluded == 0
    assert rows[0]["symbol"] == "1240"
    assert rows[0]["market"] == "TPEX"
    assert rows[0]["listing_date"] == "2018-08-08"


def test_daily_bars_are_point_in_time_versioned_and_unknown_products_are_excluded() -> None:
    source = payload(
        "TWSE",
        "daily_bars",
        [
            {
                "Date": "1150717",
                "Code": "2330",
                "TradeVolume": "1,000",
                "TradeValue": "2,000",
                "OpeningPrice": "100",
                "HighestPrice": "102",
                "LowestPrice": "99",
                "ClosingPrice": "101",
                "Transaction": "20",
            },
            {"Date": "1150717", "Code": "006208", "ClosingPrice": "120"},
        ],
    )
    rows, excluded = normalize_daily_bars(
        source,
        market="TWSE",
        source_id=8,
        security_ids={("TWSE", "2330"): 42},
    )
    assert excluded == 1
    assert len(rows) == 1
    assert rows[0]["trade_date"] == "2026-07-17"
    assert rows[0]["available_at"] == "2026-07-18T06:00:00+00:00"
    assert rows[0]["source_version"] == revision_version(source)
    assert rows[0]["company_action_complete"] is False
    assert rows[0]["opening_trade_available"] is True


def test_supabase_writer_uses_private_schema_and_never_bearer_wraps_opaque_key() -> None:
    returned = json.dumps([{"source_id": 1, "source_code": "TWSE"}]).encode()
    transport = FakeRestTransport([RestResponse(201, {}, returned)])
    writer = SupabaseWriter(
        url="https://example.supabase.co",
        server_key="sb_secret_test-value",
        transport=transport,
    )
    rows = writer.upsert(
        "data_sources",
        [{"source_code": "TWSE", "display_name": "TWSE"}],
        on_conflict="source_code",
        select="source_id,source_code",
        return_rows=True,
    )
    call = transport.calls[0]
    assert rows[0]["source_id"] == 1
    assert call["headers"]["Content-Profile"] == "market_data"
    assert call["headers"]["apikey"] == "sb_secret_test-value"
    assert "Authorization" not in call["headers"]
    assert parse_qs(urlsplit(str(call["url"])).query)["on_conflict"] == ["source_code"]
    assert "sb_secret_test-value" not in repr(writer)


def test_supabase_writer_rejects_publishable_key_before_any_request() -> None:
    with pytest.raises(IngestionError) as captured:
        SupabaseWriter(
            url="https://example.supabase.co",
            server_key="sb_publishable_wrong-side",
            transport=FakeRestTransport([]),
        )
    assert captured.value.reason_code == "SUPABASE_SERVER_KEY_REQUIRED"


def test_supabase_writer_reads_exact_count_header() -> None:
    transport = FakeRestTransport([RestResponse(200, {"Content-Range": "0-0/27"}, b"[]")])
    writer = SupabaseWriter(
        url="https://example.supabase.co",
        server_key="sb_secret_test-value",
        transport=transport,
    )
    assert writer.count_rows("daily_bars") == 27


def test_supabase_writer_selects_private_rows_with_explicit_filters() -> None:
    returned = json.dumps(
        [{"benchmark_id": 1, "benchmark_code": "TWSE_TOTAL_RETURN_INDEX"}]
    ).encode()
    transport = FakeRestTransport([RestResponse(200, {}, returned)])
    writer = SupabaseWriter(
        url="https://example.supabase.co",
        server_key="sb_secret_test-value",
        transport=transport,
    )

    rows = writer.select_rows(
        "benchmark_definitions",
        select="benchmark_id,benchmark_code",
        filters={"benchmark_code": "eq.TWSE_TOTAL_RETURN_INDEX"},
        limit=2,
    )

    assert rows == [
        {"benchmark_id": 1, "benchmark_code": "TWSE_TOTAL_RETURN_INDEX"}
    ]
    query = parse_qs(urlsplit(str(transport.calls[0]["url"])).query)
    assert query["benchmark_code"] == ["eq.TWSE_TOTAL_RETURN_INDEX"]
    assert query["limit"] == ["2"]


def test_supabase_writer_refreshes_home_status_with_private_rpc() -> None:
    transport = FakeRestTransport([RestResponse(204, {}, b"")])
    writer = SupabaseWriter(
        url="https://example.supabase.co",
        server_key="sb_secret_test-value",
        transport=transport,
    )

    writer.refresh_home_data_status()

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        "https://example.supabase.co/rest/v1/rpc/refresh_home_data_status"
    )
    assert call["body"] == b"{}"
    assert call["headers"]["Content-Profile"] == "market_data"


def test_preserve_existing_uses_ignore_duplicates_for_earliest_available_at() -> None:
    transport = FakeRestTransport([RestResponse(201, {}, b"")])
    writer = SupabaseWriter(
        url="https://example.supabase.co",
        server_key="sb_secret_test-value",
        transport=transport,
    )
    writer.upsert(
        "daily_bars",
        [{"security_id": 1, "trade_date": "2026-07-17"}],
        on_conflict="security_id,trade_date,source_id,source_version",
        preserve_existing=True,
    )
    assert "resolution=ignore-duplicates" in transport.calls[0]["headers"]["Prefer"]


def test_quality_gate_uses_actual_aligned_source_date() -> None:
    securities = [{"symbol": str(index)} for index in range(500)]
    bars = [{"trade_date": "2026-07-17"} for _ in range(500)]
    result = validate_first_stage_batch(
        requested_as_of_date=parse_exchange_date("1150718"),
        listed_securities=securities,
        otc_securities=securities,
        twse_bars=bars,
        tpex_bars=bars,
    )
    assert result.source_date.isoformat() == "2026-07-17"


def test_quality_gate_rejects_future_or_misaligned_source_dates() -> None:
    securities = [{"symbol": str(index)} for index in range(500)]
    with pytest.raises(IngestionError) as mismatch:
        validate_first_stage_batch(
            requested_as_of_date=parse_exchange_date("1150718"),
            listed_securities=securities,
            otc_securities=securities,
            twse_bars=[{"trade_date": "2026-07-17"}] * 500,
            tpex_bars=[{"trade_date": "2026-07-16"}] * 500,
        )
    assert mismatch.value.reason_code == "SOURCE_MARKET_DATE_MISMATCH"
