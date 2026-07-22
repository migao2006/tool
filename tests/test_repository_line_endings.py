from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGE_FUNCTION = "supabase/functions/prediction-snapshot"


def git_attributes(*paths: str) -> dict[str, dict[str, str]]:
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *paths],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    attributes: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        path, attribute, value = line.split(": ", maxsplit=2)
        attributes.setdefault(path, {})[attribute] = value
    return attributes


def test_deno_edge_function_files_are_forced_to_lf() -> None:
    paths = (
        f"{EDGE_FUNCTION}/index.ts",
        f"{EDGE_FUNCTION}/tests/handler_test.ts",
        f"{EDGE_FUNCTION}/deno.json",
        f"{EDGE_FUNCTION}/README.md",
    )
    attributes = git_attributes(*paths)

    assert attributes == {
        path: {"text": "set", "eol": "lf"} for path in paths
    }
