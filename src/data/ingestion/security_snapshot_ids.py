"""Strict identifier extraction for security snapshot database writes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def returned_id_map(
    rows: Sequence[Mapping[str, object]],
    *,
    code_key: str,
    id_key: str,
) -> dict[str, int]:
    resolved: dict[str, int] = {}
    for row in rows:
        code = str(row.get(code_key) or "").strip()
        raw_id = row.get(id_key)
        if not code or isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            continue
        try:
            resolved[code] = int(raw_id)
        except ValueError:
            continue
    return resolved


def returned_security_id_map(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], int]:
    resolved: dict[tuple[str, str], int] = {}
    for row in rows:
        market = str(row.get("market") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        raw_id = row.get("security_id")
        if (
            not market
            or not symbol
            or isinstance(raw_id, bool)
            or not isinstance(raw_id, (int, str))
        ):
            continue
        try:
            resolved[(market, symbol)] = int(raw_id)
        except ValueError:
            continue
    return resolved
