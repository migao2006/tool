from __future__ import annotations

from collections.abc import Sequence

import pytest

from scripts import build_tpex_research_feature_dataset as tpex_cli
from scripts import build_twse_research_feature_dataset as twse_cli
from scripts._build_venue_research_feature_dataset import VenueFeatureBuildDependencies


@pytest.mark.parametrize(
    ("module", "expected_market", "expected_reason", "identity_name", "builder_name"),
    [
        (
            twse_cli,
            "eq.TWSE",
            "TWSE_ARCHIVE_FEATURE_BUILD_FAILED",
            "TwseCurrentIdentityRepository",
            "TwseArchiveFeatureDatasetBuilder",
        ),
        (
            tpex_cli,
            "eq.TPEX",
            "TPEX_ARCHIVE_FEATURE_BUILD_FAILED",
            "TpexCurrentIdentityRepository",
            "TpexArchiveFeatureDatasetBuilder",
        ),
    ],
)
def test_venue_cli_is_a_thin_adapter_over_shared_fail_closed_builder(
    module: object,
    expected_market: str,
    expected_reason: str,
    identity_name: str,
    builder_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        argv: Sequence[str] | None,
        dependencies: VenueFeatureBuildDependencies,
    ) -> int:
        captured["argv"] = argv
        captured["dependencies"] = dependencies
        return 37

    monkeypatch.setattr(module, "run_feature_build", fake_run)
    result = module.main(["--output", "features.parquet", "--audit", "audit.json"])

    assert result == 37
    assert captured["argv"] == [
        "--output",
        "features.parquet",
        "--audit",
        "audit.json",
    ]
    dependencies = captured["dependencies"]
    assert isinstance(dependencies, VenueFeatureBuildDependencies)
    assert dependencies.archive_scope_filters["scheduled_market"] == expected_market
    assert dependencies.archive_scope_filters["asset_type"] == "eq.COMMON_STOCK"
    assert dependencies.failure_reason_code == expected_reason
    assert dependencies.identity_repository_factory.__name__ == identity_name
    assert dependencies.dataset_builder_factory.__name__ == builder_name
