from __future__ import annotations

import pytest

from src.data.ingestion.benchmark_observations import normalize_total_return_index
from src.data.ingestion.contracts import IngestionError
from tests.support.benchmark_fixtures import (
    provider_payload,
    tpex_return_index_payload,
    twse_return_index_payload,
)


@pytest.mark.parametrize(
    ("payload", "market"),
    [
        (provider_payload("TPEX", "return_index", []), "TWSE"),
        (provider_payload("TWSE", "return_index", []), "TPEX"),
        (provider_payload("TWSE", "market_index", []), "TWSE"),
    ],
)
def test_total_return_normalizer_requires_the_official_market_contract(
    payload: object, market: str
) -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_total_return_index(payload, market=market, source_id=1)

    assert captured.value.reason_code == "BENCHMARK_SOURCE_INVALID"


def test_total_return_normalizer_maps_roc_dates_and_numeric_closes() -> None:
    twse = normalize_total_return_index(
        twse_return_index_payload(), market="TWSE", source_id=11
    )
    tpex = normalize_total_return_index(
        tpex_return_index_payload(), market="TPEX", source_id=22
    )

    assert [(row["series_code"], row["numeric_value"]) for row in twse] == [
        ("TWSE_TOTAL_RETURN_INDEX", "53210.45"),
        ("TWSE_TOTAL_RETURN_INDEX", "53441.21"),
    ]
    assert [(row["series_code"], row["numeric_value"]) for row in tpex] == [
        ("TPEX_TOTAL_RETURN_INDEX", "412.34"),
        ("TPEX_TOTAL_RETURN_INDEX", "414.56"),
    ]
    assert {row["observation_at"] for row in twse} == {
        "2026-07-16T13:30:00+08:00",
        "2026-07-17T13:30:00+08:00",
    }
    assert {row["available_at"] for row in [*twse, *tpex]} == {
        "2026-07-18T06:00:00+00:00"
    }
    assert {row["source_id"] for row in twse} == {11}
    assert {row["source_id"] for row in tpex} == {22}
    assert all("sha256:" in str(row["source_version"]) for row in [*twse, *tpex])
    assert {row["usage_scope"] for row in [*twse, *tpex]} == {
        "LABEL_TARGET_ONLY"
    }
    assert {row["alignment_status"] for row in [*twse, *tpex]} == {
        "RESEARCH_ONLY"
    }
    assert all(len(str(row["source_revision_hash"])) == 64 for row in twse)
    assert all(len(str(row["source_payload_hash"])) == 64 for row in tpex)


@pytest.mark.parametrize(
    "rows",
    [
        [{"Date": "1150717", "TAIEXTotalReturnIndex": ""}],
        [{"Date": "1150717", "TAIEXTotalReturnIndex": "NaN"}],
        [{"Date": "not-a-date", "TAIEXTotalReturnIndex": "53,441.21"}],
        [{"Date": "1150717"}],
    ],
)
def test_total_return_normalizer_rejects_missing_or_invalid_twse_observations(
    rows: list[dict[str, object]],
) -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_total_return_index(
            twse_return_index_payload(rows), market="TWSE", source_id=11
        )

    assert captured.value.reason_code == "BENCHMARK_OBSERVATION_INVALID"


def test_total_return_normalizer_rejects_conflicting_duplicate_dates() -> None:
    payload = tpex_return_index_payload(
        [
            {"Date": "1150717", "TPExTotalReturnIndex": "414.56"},
            {"Date": "1150717", "TPExTotalReturnIndex": "414.57"},
        ]
    )

    with pytest.raises(IngestionError) as captured:
        normalize_total_return_index(payload, market="TPEX", source_id=22)

    assert captured.value.reason_code == "BENCHMARK_DUPLICATE_CONFLICT"


def test_total_return_normalizer_deduplicates_identical_source_rows() -> None:
    payload = twse_return_index_payload(
        [
            {"Date": "1150717", "TAIEXTotalReturnIndex": "53,441.21"},
            {"Date": "1150717", "TAIEXTotalReturnIndex": "53441.21"},
        ]
    )

    rows = normalize_total_return_index(payload, market="TWSE", source_id=11)

    assert len(rows) == 1
    assert rows[0]["numeric_value"] == "53441.21"
