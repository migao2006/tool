#!/usr/bin/env python3
"""Validate migration inventory and security contracts for patch-added SQL."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "supabase" / "migrations"
MANIFEST_PATH = ROOT / "release-manifest.json"
MIGRATION_PATTERN = re.compile(r"^(\d{14})_[a-z0-9_]+\.sql$")


class MigrationContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MigrationContractError(message)


def require_text(path: Path, checks: dict[str, str], errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing SQL file: {path.relative_to(ROOT)}")
        return
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    if not text.endswith("\n"):
        errors.append(f"{path.relative_to(ROOT)} must end with a newline")
    for label, needle in checks.items():
        if needle.lower() not in lowered:
            errors.append(f"{path.relative_to(ROOT)} is missing {label}: {needle}")


def validate() -> int:
    errors: list[str] = []
    migrations = sorted(MIGRATION_DIR.glob("*.sql"))
    names = [path.name for path in migrations]
    timestamps: list[str] = []
    for path in migrations:
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if not match:
            errors.append(f"invalid migration filename: {path.name}")
            continue
        timestamps.append(match.group(1))
        if not path.read_text(encoding="utf-8").endswith("\n"):
            errors.append(f"{path.relative_to(ROOT)} must end with a newline")
    if len(timestamps) != len(set(timestamps)):
        errors.append("migration timestamps must be unique")

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        repository = manifest["repository_state"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise MigrationContractError(
            f"Unable to load migration inventory from release-manifest.json: {error}"
        ) from error

    expected_count = repository.get("migration_file_count")
    if expected_count != len(migrations):
        errors.append(
            f"release manifest migration_file_count={expected_count!r}, repository has {len(migrations)}"
        )
    patch_names = repository.get("patch_added_migrations", [])
    if not isinstance(patch_names, list) or not all(isinstance(name, str) for name in patch_names):
        errors.append("patch_added_migrations must be a string array")
        patch_names = []
    for name in patch_names:
        if name not in names:
            errors.append(f"manifest references missing patch migration: {name}")

    rpc_migration = MIGRATION_DIR / "20260720190000_prediction_snapshot_read_rpc.sql"
    require_text(
        rpc_migration,
        {
            "transaction start": "begin;",
            "transaction commit": "commit;",
            "validation lookup index": "validation_runs_snapshot_lookup_idx",
            "explicit invoker security": "security invoker",
            "fixed search path": "set search_path = pg_catalog, market_data",
            "point-in-time observation parameter": "p_observed_at timestamptz",
            "prediction decision cutoff": "run.decision_at <= p_observed_at",
            "prediction availability cutoff": "run.latest_available_at <= p_observed_at",
            "prediction creation cutoff": "run.created_at <= p_observed_at",
            "semi-open history interval": "row.effective_to is null or v_observed_date < row.effective_to",
            "availability cutoff": "row.available_at <= p_observed_at",
            "public privilege revocation": "from public, anon, authenticated",
            "service-role grant": "to service_role",
        },
        errors,
    )
    if rpc_migration.is_file() and "security definer" in rpc_migration.read_text(encoding="utf-8").lower():
        errors.append("prediction snapshot read RPC must not use SECURITY DEFINER")

    require_text(
        ROOT / "supabase" / "snippets" / "validate_prediction_snapshot_read_rpc.sql",
        {
            "service-role privilege validation": "service_role_can_execute",
            "anonymous privilege validation": "anon_can_execute",
            "history uniqueness validation": "current_history_has_one_row_per_security",
            "point-in-time validation": "current_history_is_point_in_time_valid",
            "run point-in-time validation": "run_is_point_in_time_valid",
        },
        errors,
    )
    require_text(
        ROOT / "supabase" / "snippets" / "rollback_prediction_snapshot_read_rpc.sql",
        {
            "service-role revoke": "public, anon, authenticated, service_role",
            "function removal": "drop function if exists market_data.get_prediction_snapshot_rows",
            "index removal": "drop index if exists market_data.validation_runs_snapshot_lookup_idx",
        },
        errors,
    )

    if errors:
        raise MigrationContractError("\n".join(errors))
    return len(migrations)


def main() -> int:
    try:
        count = validate()
    except MigrationContractError as error:
        print(error)
        return 1
    print(f"SQL migration contract check passed: {count} migrations inventoried.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
