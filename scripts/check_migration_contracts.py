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
    if (
        rpc_migration.is_file()
        and "security definer" in rpc_migration.read_text(encoding="utf-8").lower()
    ):
        errors.append("prediction snapshot read RPC must not use SECURITY DEFINER")

    policy_migration = MIGRATION_DIR / "20260724044115_decision_policy_status_semantics.sql"
    require_text(
        policy_migration,
        {
            "replacement snapshot read RPC": (
                "create function market_data.get_prediction_snapshot_rows("
            ),
            "explicit invoker security": "security invoker",
            "service-role helper grant": (
                "grant execute on function market_data.get_prediction_snapshot_rows_policy_v1("
            ),
        },
        errors,
    )
    if policy_migration.is_file():
        policy_sql = policy_migration.read_text(encoding="utf-8").lower()
        marker = "create function market_data.get_prediction_snapshot_rows("
        start = policy_sql.find(marker)
        end = policy_sql.find("end\n$function$;", start)
        if start < 0 or end < 0:
            errors.append("decision-policy migration snapshot read RPC definition is incomplete")
        else:
            active_read_rpc = policy_sql[start:end]
            if "security invoker" not in active_read_rpc:
                errors.append("active decision-policy snapshot read RPC must use SECURITY INVOKER")
            if "security definer" in active_read_rpc:
                errors.append(
                    "active decision-policy snapshot read RPC must not use SECURITY DEFINER"
                )

    require_text(
        ROOT / "supabase" / "snippets" / "validate_prediction_snapshot_read_rpc.sql",
        {
            "service-role privilege validation": "service_role_can_execute",
            "anonymous privilege validation": "anon_can_execute",
            "invoker validation": "security_invoker",
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

    calendar_migration = MIGRATION_DIR / "20260721090000_prediction_snapshot_calendar_freshness.sql"
    require_text(
        calendar_migration,
        {
            "transaction start": "begin;",
            "transaction commit": "commit;",
            "calendar lookup index": "trading_calendar_observations_freshness_idx",
            "versioned snapshot function": "get_prediction_snapshot_rows_v2",
            "single base snapshot call": "select market_data.get_prediction_snapshot_rows(",
            "verified observations": "calendar_verification_status = 'VERIFIED'",
            "source asserted observations": "market_basis = 'SOURCE_ASSERTED'",
            "point-in-time usage": "usage_scope = 'POINT_IN_TIME_CALENDAR'",
            "passing observations": "system_status = 'PASS'",
            "calendar availability cutoff": "row.available_at <= p_observed_at",
            "bounded calendar lookback": "::date - 62",
            "explicit invoker security": "security invoker",
            "fixed search path": "set search_path = pg_catalog, market_data",
            "public privilege revocation": "from public, anon, authenticated",
            "service-role grant": "to service_role",
        },
        errors,
    )
    if (
        calendar_migration.is_file()
        and "security definer" in calendar_migration.read_text(encoding="utf-8").lower()
    ):
        errors.append("calendar freshness RPC must not use SECURITY DEFINER")

    require_text(
        ROOT / "supabase" / "snippets" / "validate_prediction_snapshot_calendar_freshness.sql",
        {
            "service-role privilege validation": "service_role_can_execute",
            "anonymous privilege validation": "anon_can_execute",
            "invoker validation": "security_invoker",
            "verified-calendar validation": "verified_calendar_is_embedded",
            "point-in-time validation": "calendar_is_point_in_time_valid",
        },
        errors,
    )
    require_text(
        ROOT / "supabase" / "snippets" / "rollback_prediction_snapshot_calendar_freshness.sql",
        {
            "service-role revoke": "public, anon, authenticated, service_role",
            "function removal": "drop function if exists market_data.get_prediction_snapshot_rows_v2",
            "index removal": "drop index if exists market_data.trading_calendar_observations_freshness_idx",
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
