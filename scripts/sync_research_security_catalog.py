"""Synchronize validated business identities into the isolated staging database."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
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
    sync_research_security_catalog,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize one validated research security catalog to staging."
    )
    _ = parser.add_argument("--market", choices=("TWSE", "TPEX"), required=True)
    _ = parser.add_argument("--catalog", type=Path, required=True)
    return parser


def _load(path: Path) -> dict[str, object]:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IngestionError(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security catalog JSON could not be read",
        ) from error
    if not isinstance(value, Mapping):
        raise IngestionError(
            "RESEARCH_SECURITY_CATALOG_INVALID",
            "Research security catalog JSON is not an object",
        )
    return dict(cast(Mapping[str, object], value))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    market = cast(str, arguments.market)
    catalog_path = cast(Path, arguments.catalog)
    try:
        if os.environ.get("ALPHA_LENS_TARGET_ENVIRONMENT") != "staging":
            raise IngestionError(
                "RESEARCH_SECURITY_CATALOG_TARGET_INVALID",
                "Research security catalog synchronization is staging-only",
            )
        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        result = sync_research_security_catalog(
            writer,
            _load(catalog_path),
            market=market,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
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
                        "RESEARCH_SECURITY_CATALOG_SYNC_FAILED",
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
