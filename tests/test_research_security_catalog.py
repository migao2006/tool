from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import cast

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.research.staging_security_catalog import (
    export_research_security_catalog,
    sync_research_security_catalog,
)


class FakeCatalogWriter:
    def __init__(
        self,
        *,
        sources: Sequence[Mapping[str, object]],
        securities: Sequence[Mapping[str, object]],
        omitted_source: str | None = None,
        omitted_security: str | None = None,
        corrupt_source: str | None = None,
        corrupt_security: str | None = None,
    ) -> None:
        self.sources = [dict(row) for row in sources]
        self.securities = [dict(row) for row in securities]
        self.omitted_source = omitted_source
        self.omitted_security = omitted_security
        self.corrupt_source = corrupt_source
        self.corrupt_security = corrupt_security
        self.calls: list[dict[str, object]] = []

    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        page_size: int = 1_000,
        max_rows: int = 10_000,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "operation": "select",
                "table": table,
                "select": select,
                "filters": dict(filters or {}),
                "page_size": page_size,
                "max_rows": max_rows,
            }
        )
        rows = self.sources if table == "data_sources" else self.securities
        market_filter = str((filters or {}).get("market") or "")
        asset_filter = str((filters or {}).get("asset_type") or "")
        return [
            dict(row)
            for row in rows
            if (not market_filter or market_filter == f"eq.{row.get('market')}")
            and (not asset_filter or asset_filter == f"eq.{row.get('asset_type')}")
        ]

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        materialized = [dict(row) for row in rows]
        self.calls.append(
            {
                "operation": "upsert",
                "table": table,
                "rows": materialized,
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        if table == "data_sources":
            return [
                {
                    **row,
                    "source_id": 700 + index,
                    "display_name": (
                        "corrupt"
                        if row["source_code"] == self.corrupt_source
                        else row["display_name"]
                    ),
                }
                for index, row in enumerate(materialized)
                if row["source_code"] != self.omitted_source
            ]
        if table == "securities":
            return [
                {
                    **row,
                    "security_id": 900 + index,
                    "display_name": (
                        "corrupt"
                        if row["symbol"] == self.corrupt_security
                        else row["display_name"]
                    ),
                }
                for index, row in enumerate(materialized)
                if row["symbol"] != self.omitted_security
            ]
        return []


def _sources() -> list[dict[str, object]]:
    return [
        {
            "source_id": 11,
            "source_code": "MOPS",
            "display_name": "公開資訊觀測站",
            "source_timezone": "Asia/Taipei",
            "revision_policy": "PAYLOAD_HASH_VERSIONED",
            "is_active": True,
        }
    ]


def _securities() -> list[dict[str, object]]:
    return [
        {
            "security_id": 101,
            "symbol": "2330",
            "display_name": "台積電",
            "market": "TWSE",
            "asset_type": "COMMON_STOCK",
            "currency": "TWD",
            "listing_date": "1994-09-05",
            "delisting_date": None,
            "isin": "TW0002330008",
            "source_id": 11,
        },
        {
            "security_id": 102,
            "symbol": "1101",
            "display_name": "台泥",
            "market": "TWSE",
            "asset_type": "COMMON_STOCK",
            "currency": "TWD",
            "listing_date": "1962-02-09",
            "delisting_date": None,
            "isin": None,
            "source_id": 11,
        },
        {
            "security_id": 103,
            "symbol": "006208",
            "display_name": "富邦台50",
            "market": "TWSE",
            "asset_type": "ETF",
            "currency": "TWD",
            "listing_date": "2012-06-22",
            "delisting_date": None,
            "isin": None,
            "source_id": 11,
        },
        {
            "security_id": 104,
            "symbol": "6488",
            "display_name": "環球晶",
            "market": "TPEX",
            "asset_type": "COMMON_STOCK",
            "currency": "TWD",
            "listing_date": "2015-09-25",
            "delisting_date": None,
            "isin": None,
            "source_id": 11,
        },
    ]


def test_export_is_deterministic_sanitized_and_venue_asset_isolated() -> None:
    first_writer = FakeCatalogWriter(
        sources=_sources(),
        securities=list(reversed(_securities())),
    )
    second_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())

    first = export_research_security_catalog(first_writer, market="TWSE")
    second = export_research_security_catalog(second_writer, market="TWSE")

    assert first == second
    assert first["schema_version"] == "research-security-catalog.v1"
    assert first["system_status"] == "RESEARCH_ONLY"
    assert first["market"] == "TWSE"
    assert first["asset_type"] == "COMMON_STOCK"
    assert first["row_count"] == 2
    rows = cast(list[dict[str, object]], first["securities"])
    assert [row["symbol"] for row in rows] == ["1101", "2330"]
    assert all("security_id" not in row and "source_id" not in row for row in rows)
    assert all(row["market"] == "TWSE" for row in rows)
    assert all(row["asset_type"] == "COMMON_STOCK" for row in rows)
    assert len(str(first["catalog_sha256"])) == 64
    securities_call = first_writer.calls[0]
    assert securities_call["filters"] == {
        "market": "eq.TWSE",
        "asset_type": "eq.COMMON_STOCK",
        "order": "symbol.asc",
    }


def test_sync_maps_source_to_staging_id_and_verifies_all_securities() -> None:
    export_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())
    catalog = export_research_security_catalog(export_writer, market="TWSE")
    staging_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())

    result = sync_research_security_catalog(
        staging_writer,
        catalog,
        market="TWSE",
    )

    assert result == {
        "schema_version": "research-security-catalog.v1",
        "market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "row_count": 2,
        "catalog_sha256": catalog["catalog_sha256"],
        "system_status": "RESEARCH_ONLY",
        "status": "PASS",
    }
    upserts = [
        call for call in staging_writer.calls if call["operation"] == "upsert"
    ]
    assert [call["table"] for call in upserts] == ["data_sources", "securities"]
    security_rows = cast(list[dict[str, object]], upserts[1]["rows"])
    assert {row["source_id"] for row in security_rows} == {700}
    assert all("security_id" not in row for row in security_rows)
    assert all(row["market"] == "TWSE" for row in security_rows)
    assert all(row["asset_type"] == "COMMON_STOCK" for row in security_rows)


def test_tampered_catalog_fails_before_any_staging_write() -> None:
    export_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())
    catalog = deepcopy(export_research_security_catalog(export_writer, market="TWSE"))
    rows = cast(list[dict[str, object]], catalog["securities"])
    rows[0]["display_name"] = "tampered"
    staging_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())

    with pytest.raises(IngestionError) as captured:
        sync_research_security_catalog(staging_writer, catalog, market="TWSE")

    assert captured.value.reason_code == "RESEARCH_SECURITY_CATALOG_HASH_MISMATCH"
    assert staging_writer.calls == []


def test_catalog_market_mismatch_fails_before_any_staging_write() -> None:
    export_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())
    catalog = export_research_security_catalog(export_writer, market="TWSE")
    staging_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())

    with pytest.raises(IngestionError) as captured:
        sync_research_security_catalog(staging_writer, catalog, market="TPEX")

    assert captured.value.reason_code == "RESEARCH_SECURITY_CATALOG_SCOPE_MISMATCH"
    assert staging_writer.calls == []


def test_export_rejects_tdr_even_if_source_mislabels_it_common_stock() -> None:
    securities = _securities()
    securities.append(
        {
            "security_id": 105,
            "symbol": "9103",
            "display_name": "美德醫療-DR",
            "market": "TWSE",
            "asset_type": "COMMON_STOCK",
            "currency": "TWD",
            "listing_date": "2002-12-13",
            "delisting_date": None,
            "isin": None,
            "source_id": 11,
        }
    )
    writer = FakeCatalogWriter(sources=_sources(), securities=securities)

    with pytest.raises(IngestionError) as captured:
        export_research_security_catalog(writer, market="TWSE")

    assert captured.value.reason_code == "RESEARCH_SECURITY_CATALOG_SCOPE_MISMATCH"


def test_incomplete_staging_source_upsert_fails_before_security_write() -> None:
    export_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())
    catalog = export_research_security_catalog(export_writer, market="TWSE")
    staging_writer = FakeCatalogWriter(
        sources=_sources(),
        securities=_securities(),
        omitted_source="MOPS",
    )

    with pytest.raises(IngestionError) as captured:
        sync_research_security_catalog(staging_writer, catalog, market="TWSE")

    assert captured.value.reason_code == "RESEARCH_SECURITY_SOURCE_SYNC_INCOMPLETE"
    upserts = [
        call for call in staging_writer.calls if call["operation"] == "upsert"
    ]
    assert [call["table"] for call in upserts] == ["data_sources"]


def test_incomplete_staging_security_upsert_fails_closed() -> None:
    export_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())
    catalog = export_research_security_catalog(export_writer, market="TWSE")
    staging_writer = FakeCatalogWriter(
        sources=_sources(),
        securities=_securities(),
        omitted_security="2330",
    )

    with pytest.raises(IngestionError) as captured:
        sync_research_security_catalog(staging_writer, catalog, market="TWSE")

    assert captured.value.reason_code == "RESEARCH_SECURITY_SYNC_INCOMPLETE"


def test_staging_source_semantic_readback_mismatch_fails_before_security_write() -> None:
    export_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())
    catalog = export_research_security_catalog(export_writer, market="TWSE")
    staging_writer = FakeCatalogWriter(
        sources=_sources(),
        securities=_securities(),
        corrupt_source="MOPS",
    )

    with pytest.raises(IngestionError) as captured:
        sync_research_security_catalog(staging_writer, catalog, market="TWSE")

    assert captured.value.reason_code == "RESEARCH_SECURITY_SOURCE_SYNC_MISMATCH"
    upserts = [
        call for call in staging_writer.calls if call["operation"] == "upsert"
    ]
    assert [call["table"] for call in upserts] == ["data_sources"]


def test_staging_semantic_readback_mismatch_fails_closed() -> None:
    export_writer = FakeCatalogWriter(sources=_sources(), securities=_securities())
    catalog = export_research_security_catalog(export_writer, market="TWSE")
    staging_writer = FakeCatalogWriter(
        sources=_sources(),
        securities=_securities(),
        corrupt_security="2330",
    )

    with pytest.raises(IngestionError) as captured:
        sync_research_security_catalog(staging_writer, catalog, market="TWSE")

    assert captured.value.reason_code == "RESEARCH_SECURITY_SYNC_MISMATCH"
