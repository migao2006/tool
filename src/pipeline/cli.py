"""Command-line interface for auditable five-day pipeline orchestration."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Sequence

from .contracts import PipelineMode, PipelineRunner
from .orchestrator import PipelineOrchestrator
from .repositories import (
    DataSourceError,
    FileDatasetRepository,
    load_object,
    repository_from_reference,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "five_day_mvp.toml"


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha-lens-pipeline",
        description="Train, backtest, or infer the production five-trading-day MVP.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in PipelineMode:
        command = subparsers.add_parser(mode.value)
        command.add_argument("--horizon", type=int, default=5)
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        command.add_argument("--artifact-root", type=Path, default=PROJECT_ROOT / "artifacts")
        source = command.add_mutually_exclusive_group()
        source.add_argument("--input", type=Path, help="real CSV or Parquet input")
        source.add_argument(
            "--repository",
            help="repository object in module:attribute form; it must implement DatasetRepository",
        )
        command.add_argument(
            "--runner",
            help="model/backtest runner in module:attribute form; no runner means RESEARCH_ONLY",
        )
        command.add_argument("--report", type=Path, help="optional JSON run report")
        if mode is PipelineMode.INFER:
            command.add_argument("--as-of-date", type=_date, required=True)
    return parser


def _emit(payload: dict[str, object], report: Path | None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    mode = PipelineMode(args.mode)
    try:
        repository = None
        if args.input is not None:
            repository = FileDatasetRepository(args.input)
        elif args.repository:
            repository = repository_from_reference(args.repository)

        runner = None
        if args.runner:
            candidate = load_object(args.runner)
            if not isinstance(candidate, PipelineRunner):
                raise DataSourceError(f"{args.runner} does not implement PipelineRunner")
            runner = candidate

        result = PipelineOrchestrator(
            config_path=args.config,
            artifact_root=args.artifact_root,
        ).run(
            mode=mode,
            horizon=args.horizon,
            repository=repository,
            runner=runner,
            as_of_date=getattr(args, "as_of_date", None),
        )
        _emit(result.to_dict(), args.report)
        return result.exit_code
    except (DataSourceError, FileNotFoundError, KeyError, NotImplementedError, ValueError) as error:
        payload: dict[str, object] = {
            "mode": mode.value,
            "horizon": args.horizon,
            "status": "FAIL",
            "reason_codes": ["PIPELINE_CONFIGURATION_ERROR"],
            "message": str(error),
            "metrics": {},
            "artifacts": {},
        }
        _emit(payload, args.report)
        return 1


if __name__ == "__main__":
    sys.exit(main())
