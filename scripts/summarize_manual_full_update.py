"""Build the sanitized artifact and GitHub summary for one manual full update."""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
from typing import Sequence, cast

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.pipeline.manual_full_update_contract import (  # noqa: E402
    render_manual_full_update_markdown,
    summarize_manual_full_update,
)


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compose the fail-closed manual full-update evidence summary."
    )
    _ = parser.add_argument("--import-result", type=Path, required=True)
    _ = parser.add_argument("--resolution-result", type=Path, required=True)
    _ = parser.add_argument("--twse-production-verification", type=Path, required=True)
    _ = parser.add_argument("--tpex-production-verification", type=Path, required=True)
    _ = parser.add_argument("--actor", required=True)
    _ = parser.add_argument("--repository", required=True)
    _ = parser.add_argument("--branch", required=True)
    _ = parser.add_argument("--sha", required=True)
    _ = parser.add_argument("--run-id", type=int, required=True)
    _ = parser.add_argument("--run-attempt", type=int, required=True)
    _ = parser.add_argument("--requested-as-of-date")
    _ = parser.add_argument("--dry-run", type=_boolean, required=True)
    _ = parser.add_argument("--publish-production", type=_boolean, required=True)
    _ = parser.add_argument("--production-publish-enabled", type=_boolean, required=True)
    _ = parser.add_argument("--preflight-result", required=True)
    _ = parser.add_argument("--import-job-result", required=True)
    _ = parser.add_argument("--research-job-result", required=True)
    _ = parser.add_argument("--output", type=Path, required=True)
    _ = parser.add_argument("--markdown-output", type=Path, required=True)
    return parser


def _optional_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    payload = summarize_manual_full_update(
        import_raw=_optional_bytes(cast(Path, arguments.import_result)),
        resolution_raw=_optional_bytes(cast(Path, arguments.resolution_result)),
        production_raw={
            "TWSE": _optional_bytes(
                cast(Path, arguments.twse_production_verification)
            ),
            "TPEX": _optional_bytes(
                cast(Path, arguments.tpex_production_verification)
            ),
        },
        actor=cast(str, arguments.actor),
        repository=cast(str, arguments.repository),
        branch=cast(str, arguments.branch),
        sha=cast(str, arguments.sha),
        run_id=cast(int, arguments.run_id),
        run_attempt=cast(int, arguments.run_attempt),
        requested_as_of_date=cast(str | None, arguments.requested_as_of_date),
        dry_run=cast(bool, arguments.dry_run),
        publish_production=cast(bool, arguments.publish_production),
        production_publish_enabled=cast(
            bool,
            arguments.production_publish_enabled,
        ),
        preflight_result=cast(str, arguments.preflight_result),
        import_job_result=cast(str, arguments.import_job_result),
        research_job_result=cast(str, arguments.research_job_result),
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    markdown = render_manual_full_update_markdown(payload)
    output = cast(Path, arguments.output)
    markdown_output = cast(Path, arguments.markdown_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(rendered, encoding="utf-8")
    with markdown_output.open("a", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(markdown)
    print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
