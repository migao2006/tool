"""Make direct ``python scripts/*.py`` execution resolve the project package."""

from __future__ import annotations

from pathlib import Path
import sys


def add_project_root() -> None:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
