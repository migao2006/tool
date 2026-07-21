"""Report API credential readiness and optionally run small live probes."""

from __future__ import annotations

import argparse
from datetime import date
import json
import sys
from typing import Sequence

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root

add_project_root()

from src.data.providers.health import run_live_probes  # noqa: E402
from src.data.providers.registry import (  # noqa: E402
    build_provider_registry,
    provider_readiness,
)
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Alpha Lens market-data APIs.")
    parser.add_argument("--live", action="store_true", help="perform small real API requests")
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=date.today())
    return parser


def build_report(*, live: bool, as_of_date: date) -> tuple[dict[str, object], int]:
    settings = ApiProviderSettings.from_env()
    readiness = provider_readiness(settings)
    report: dict[str, object] = {
        "as_of_date": as_of_date.isoformat(),
        "mode": "live" if live else "configuration",
        "providers": [
            {
                "provider": item.provider,
                "configured": item.configured,
                "required_environment_variables": list(item.credential_environment_variables),
                "reason_code": item.reason_code,
            }
            for item in readiness
        ],
    }
    if not live:
        report["status"] = "PASS" if all(item.configured for item in readiness) else "RESEARCH_ONLY"
        return report, 0

    probes = run_live_probes(
        build_provider_registry(settings),
        as_of_date=as_of_date,
    )
    report["probes"] = [probe.to_dict() for probe in probes]
    failures = [probe for probe in probes if probe.status == "FAIL"]
    missing = [probe for probe in probes if probe.status == "NOT_CONFIGURED"]
    degraded = [probe for probe in probes if probe.status == "DEGRADED"]
    report["status"] = (
        "FAIL"
        if failures
        else "RESEARCH_ONLY"
        if missing or degraded
        else "PASS"
    )
    return report, 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report, exit_code = build_report(live=args.live, as_of_date=args.as_of_date)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
