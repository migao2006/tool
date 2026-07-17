"""Backtest supplied point-in-time decisions using the configured runner."""

from __future__ import annotations

import sys

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root

add_project_root()

from src.pipeline.cli import main


if __name__ == "__main__":
    sys.exit(main(["backtest", *sys.argv[1:]]))
