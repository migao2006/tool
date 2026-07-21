"""Safe normalization and classification for Supabase server API keys."""

from __future__ import annotations

from enum import StrEnum


class SupabaseKeyKind(StrEnum):
    OPAQUE_SECRET = "opaque_secret"
    PUBLISHABLE = "publishable"
    LEGACY_JWT = "legacy_jwt"
    UNKNOWN = "unknown"


def normalize_server_key(value: str | None) -> str | None:
    """Normalize common secret paste forms without logging the credential."""

    if not value:
        return None
    normalized = value.strip()
    for _ in range(2):
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "\"'":
            normalized = normalized[1:-1].strip()
        for variable in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"):
            if normalized.upper().startswith(f"{variable}="):
                normalized = normalized.split("=", 1)[1].strip()
                break
    return normalized or None


def classify_server_key(value: str) -> SupabaseKeyKind:
    """Return only a non-sensitive key category for diagnostics."""

    if value.startswith("sb_secret_"):
        return SupabaseKeyKind.OPAQUE_SECRET
    if value.startswith("sb_publishable_"):
        return SupabaseKeyKind.PUBLISHABLE
    if value.count(".") == 2:
        return SupabaseKeyKind.LEGACY_JWT
    return SupabaseKeyKind.UNKNOWN


def rejected_key_reason(kind: SupabaseKeyKind) -> str:
    return {
        SupabaseKeyKind.OPAQUE_SECRET: "SUPABASE_SECRET_KEY_REJECTED",
        SupabaseKeyKind.PUBLISHABLE: "SUPABASE_SERVER_KEY_REQUIRED",
        SupabaseKeyKind.LEGACY_JWT: "SUPABASE_LEGACY_SERVICE_ROLE_KEY_REJECTED",
        SupabaseKeyKind.UNKNOWN: "SUPABASE_SERVER_KEY_FORMAT_INVALID",
    }[kind]
