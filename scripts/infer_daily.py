"""Run one as-of daily inference using frozen artifacts and real inputs."""

from __future__ import annotations

import sys

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root

add_project_root()

from src.pipeline.cli import main


if __name__ == "__main__":
    sys.exit(main(["infer", *sys.argv[1:]]))
