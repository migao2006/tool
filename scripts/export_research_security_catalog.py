"""Export a sanitized production security catalog for isolated research staging."""

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
from src.data.research.staging_security_catalog import (  # noqa: E402
    export_research_security_catalog,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export environment-neutral research security business identities."
    )
    _ = parser.add_argument("--market", choices=("TWSE", "TPEX"), required=True)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    market = cast(str, arguments.market)
    output = cast(Path, arguments.output)
    try:
        if os.environ.get("ALPHA_LENS_SOURCE_ENVIRONMENT") != "production":
            raise IngestionError(
                "RESEARCH_SECURITY_CATALOG_SOURCE_INVALID",
                "Research security catalog export requires the production source",
            )
        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        payload = export_research_security_catalog(writer, market=market)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
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
                        "RESEARCH_SECURITY_CATALOG_EXPORT_FAILED",
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
