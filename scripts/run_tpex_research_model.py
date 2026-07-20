"""Run the isolated TPEX purged walk-forward research model locally."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys
from typing import cast

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.config.loader import DEFAULT_CONFIG_PATH  # noqa: E402
from src.pipeline.contracts import PipelineMode, PipelineStatus  # noqa: E402
from src.pipeline.orchestrator import PipelineOrchestrator  # noqa: E402
from src.pipeline.tpex_research_runner import (  # noqa: E402
    tpex_price_research_runner,
)
from src.pipeline.twse_prepared_research_repository import (  # noqa: E402
    PreparedResearchArtifactRepository,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the TPEX rank, direction, and quantile models on one verified "
            "prepared artifact. Outputs remain RESEARCH_ONLY."
        )
    )
    _ = parser.add_argument("--input", required=True, type=Path)
    _ = parser.add_argument("--input-audit", required=True, type=Path)
    _ = parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    _ = parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    _ = parser.add_argument("--report", type=Path)
    _ = parser.add_argument("--horizon", type=int, default=5)
    return parser


def _write_report(path: Path | None, payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    horizon = cast(int, arguments.horizon)
    report = cast(Path | None, arguments.report)
    if horizon != 5:
        _write_report(
            report,
            {
                "mode": "train",
                "market": "TPEX",
                "horizon": horizon,
                "status": "FAIL",
                "reason_codes": ["UNSUPPORTED_HORIZON"],
                "artifacts": {},
            },
        )
        return 1
    result = PipelineOrchestrator(
        config_path=cast(Path, arguments.config),
        artifact_root=cast(Path, arguments.artifact_root),
    ).run(
        mode=PipelineMode.TRAIN,
        horizon=horizon,
        repository=PreparedResearchArtifactRepository(
            cast(Path, arguments.input),
            cast(Path, arguments.input_audit),
            expected_market="TPEX",
        ),
        runner=tpex_price_research_runner,
    )
    payload = cast(dict[str, object], result.to_dict())
    payload["market"] = "TPEX"
    _write_report(report, payload)
    has_snapshot = bool(result.artifacts.get("research_prediction_snapshot"))
    if result.status is PipelineStatus.RESEARCH_ONLY and has_snapshot:
        return 0
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
