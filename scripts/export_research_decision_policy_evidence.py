"""Export point-in-time Decision Policy evidence from Production."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path
import sys
from typing import cast

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.research.decision_policy_evidence_export import (  # noqa: E402
    export_decision_policy_evidence,
)
from src.pipeline.tpex_latest_feature_repository import (  # noqa: E402
    LatestTpexFeatureRepository,
)
from src.pipeline.twse_latest_feature_repository import (  # noqa: E402
    LatestTwseFeatureRepository,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export exact-date, pre-decision policy evidence for one immutable "
            "research feature universe."
        )
    )
    _ = parser.add_argument("--market", choices=("TWSE", "TPEX"), required=True)
    _ = parser.add_argument("--feature-input", type=Path, required=True)
    _ = parser.add_argument("--feature-audit", type=Path, required=True)
    _ = parser.add_argument("--publication-id", required=True)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    market = cast(str, arguments.market)
    output = cast(Path, arguments.output)
    try:
        if os.environ.get("ALPHA_LENS_SOURCE_ENVIRONMENT") != "production":
            raise IngestionError(
                "DECISION_POLICY_EVIDENCE_SOURCE_INVALID",
                "Decision Policy evidence export requires the production source",
            )
        repository = (
            LatestTwseFeatureRepository()
            if market == "TWSE"
            else LatestTpexFeatureRepository()
        )
        cross_section = repository.load(
            cast(Path, arguments.feature_input),
            cast(Path, arguments.feature_audit),
        )
        securities = {
            str(row.symbol): int(row.security_id)
            for row in cross_section.frame.itertuples(index=False)
        }
        if len(securities) != len(cross_section.frame):
            raise ValueError("Decision Policy evidence universe identities are not unique")
        decision_ats = {
            value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
            for value in cross_section.frame["decision_at"]
        }
        if len(decision_ats) != 1:
            raise ValueError("Decision Policy evidence universe has mixed decision_at")
        decision_at = next(iter(decision_ats))
        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        snapshot = export_decision_policy_evidence(
            writer,
            market=market,
            as_of_date=cross_section.as_of_date,
            decision_at=decision_at,
            securities=securities,
            publication_id=cast(str, arguments.publication_id),
        )
        rendered = json.dumps(
            snapshot.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        _ = output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except (IngestionError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "market": market,
                    "reason_code": getattr(
                        error,
                        "reason_code",
                        "DECISION_POLICY_EVIDENCE_EXPORT_FAILED",
                    ),
                    "message": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
