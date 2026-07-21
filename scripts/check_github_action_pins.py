#!/usr/bin/env python3
"""Validate every external GitHub Action against the reviewed immutable pin set."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PIN_PATH = ROOT / "config" / "github-actions-pins.json"
USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^'\"\s#]+)")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DOCKER_DIGEST_PATTERN = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")
VERSION_COMMENT_PATTERN = re.compile(r"#\s*(v[^\s]+)\s*$")


def load_reviewed_pins() -> dict[str, dict[str, str]]:
    """Return the validated immutable Action pin registry."""
    payload = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    raw_pins = payload.get("actions")
    if not isinstance(raw_pins, dict):
        raise ValueError("config/github-actions-pins.json must define an actions object")

    pins: dict[str, dict[str, str]] = {}
    for action, raw_metadata in raw_pins.items():
        if not isinstance(action, str) or not isinstance(raw_metadata, dict):
            raise ValueError("invalid GitHub Action pin registry entry")
        sha = raw_metadata.get("sha")
        version = raw_metadata.get("version")
        if not isinstance(sha, str) or not isinstance(version, str):
            raise ValueError(f"invalid GitHub Action pin metadata for {action}")
        pins[action] = {"sha": sha, "version": version}
    return pins


def reviewed_action_reference(action: str) -> str:
    """Build the exact immutable workflow reference for a reviewed Action."""
    pins = load_reviewed_pins()
    try:
        return f"{action}@{pins[action]['sha']}"
    except KeyError as exc:
        raise ValueError(f"unreviewed GitHub Action: {action}") from exc


def main() -> int:
    errors: list[str] = []
    try:
        pins = load_reviewed_pins()
    except ValueError as exc:
        print(str(exc))
        return 1

    checked = 0
    used_actions: set[str] = set()
    for path in sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES_PATTERN.match(line)
            if not match:
                continue
            reference = match.group(1)
            if reference.startswith("./"):
                continue
            checked += 1
            location = f"{path.relative_to(ROOT)}:{line_number}"
            if reference.startswith("docker://"):
                if not DOCKER_DIGEST_PATTERN.fullmatch(reference):
                    errors.append(f"{location}: Docker action must use a sha256 digest: {reference}")
                continue

            action, separator, revision = reference.rpartition("@")
            if not separator or "/" not in action or not SHA_PATTERN.fullmatch(revision):
                errors.append(
                    f"{location}: external action must use a full 40-character commit SHA: {reference}"
                )
                continue
            used_actions.add(action)
            expected = pins.get(action)
            if not isinstance(expected, dict):
                errors.append(f"{location}: action is not in the reviewed pin registry: {action}")
                continue
            expected_sha = expected.get("sha")
            expected_version = expected.get("version")
            if revision != expected_sha:
                errors.append(
                    f"{location}: {action} uses {revision}, expected reviewed SHA {expected_sha}"
                )
            version_match = VERSION_COMMENT_PATTERN.search(line)
            if not version_match or version_match.group(1) != expected_version:
                errors.append(
                    f"{location}: pin comment must be '# {expected_version}' for {action}"
                )

    stale = sorted(set(pins) - used_actions)
    if stale:
        errors.append("reviewed pin registry contains unused actions: " + ", ".join(stale))
    for action, metadata in pins.items():
        if not isinstance(metadata, dict):
            errors.append(f"invalid pin metadata for {action}")
            continue
        if not SHA_PATTERN.fullmatch(str(metadata.get("sha", ""))):
            errors.append(f"invalid SHA in pin registry for {action}")
        if not re.fullmatch(r"v\d+(?:\.\d+){0,2}", str(metadata.get("version", ""))):
            errors.append(f"invalid version label in pin registry for {action}")

    if errors:
        print("\n".join(errors))
        return 1
    print(
        f"GitHub Action pin check passed: {checked} references match "
        f"{len(used_actions)} reviewed immutable pins."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
