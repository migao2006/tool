"""Build a feature-only TWSE research dataset from private verified archives."""

from __future__ import annotations

from collections.abc import Sequence
import sys

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from scripts._build_venue_research_feature_dataset import (  # noqa: E402
    VenueFeatureBuildDependencies,
    run_feature_build,
)

from src.data.archive.historical_parquet_reader import HistoricalParquetReader  # noqa: E402
from src.data.archive.manifest_repository import (  # noqa: E402
    HistoricalArchiveManifestRepository,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.data.research.twse_archive_feature_builder import (  # noqa: E402
    TwseArchiveFeatureDatasetBuilder,
)
from src.data.research.twse_archive_feature_contracts import (  # noqa: E402
    TWSE_ARCHIVE_SCOPE_FILTERS,
    dataset_snapshot_hash,
)
from src.data.research.twse_archive_feature_parquet import (  # noqa: E402
    TwseArchiveFeatureParquetWriter,
)
from src.data.research.twse_feature_artifact_reader import (  # noqa: E402
    TwseFeatureArtifactReader,
)
from src.data.research.twse_current_identity_repository import (  # noqa: E402
    TwseCurrentIdentityRepository,
)


def main(argv: Sequence[str] | None = None) -> int:
    return run_feature_build(
        argv,
        VenueFeatureBuildDependencies(
            market="TWSE",
            description=(
                "Stream fully verified TWSE daily-bar archives into a "
                "RESEARCH_ONLY price/volume feature dataset."
            ),
            archive_scope_filters=TWSE_ARCHIVE_SCOPE_FILTERS,
            failure_reason_code="TWSE_ARCHIVE_FEATURE_BUILD_FAILED",
            supabase_writer_factory=SupabaseWriter,
            manifest_repository_factory=HistoricalArchiveManifestRepository,
            identity_repository_factory=TwseCurrentIdentityRepository,
            r2_client_factory=R2Client.from_env,
            historical_reader_factory=HistoricalParquetReader,
            dataset_snapshot_hash=dataset_snapshot_hash,
            parquet_writer_factory=TwseArchiveFeatureParquetWriter,
            dataset_builder_factory=TwseArchiveFeatureDatasetBuilder,
            artifact_reader_factory=TwseFeatureArtifactReader,
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
