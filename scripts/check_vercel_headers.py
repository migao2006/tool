#!/usr/bin/env python3
"""Validate Vercel response headers and strict-CSP source compatibility."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "vercel.json"
REQUIRED_HEADERS = {
    "content-security-policy",
    "referrer-policy",
    "x-content-type-options",
    "x-frame-options",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "x-permitted-cross-domain-policies",
    "strict-transport-security",
}
REQUIRED_CSP = {
    "default-src": {"'self'"},
    "base-uri": {"'self'"},
    "object-src": {"'none'"},
    "frame-ancestors": {"'none'"},
    "form-action": {"'self'"},
    "script-src": {"'self'"},
    "script-src-attr": {"'none'"},
    "style-src": {"'self'"},
    "style-src-attr": {"'none'"},
}
REQUIRED_CONNECT_SOURCES = {
    "'self'",
    "https://zuhwkxlmnvwiktcmijup.supabase.co",
    "wss://zuhwkxlmnvwiktcmijup.supabase.co",
    "https://o4511751659651072.ingest.us.sentry.io",
}
INLINE_HTML_PATTERNS = {
    "inline script": re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE),
    "inline style element": re.compile(r"<style\b", re.IGNORECASE),
    "style attribute": re.compile(r"\sstyle\s*=", re.IGNORECASE),
    "inline event handler": re.compile(r"\son[a-z]+\s*=", re.IGNORECASE),
}
DYNAMIC_STYLE_PATTERN = re.compile(
    r"(?:\.style\b|setAttribute\(\s*['\"]style['\"]|style\.cssText)",
)
UNSAFE_SCRIPT_PATTERN = re.compile(r"(?:\beval\s*\(|\bnew\s+Function\s*\()")


def parse_csp(value: str) -> dict[str, set[str]]:
    directives: dict[str, set[str]] = {}
    for chunk in value.split(";"):
        parts = chunk.strip().split()
        if not parts:
            continue
        directives[parts[0].lower()] = set(parts[1:])
    return directives


def main() -> int:
    errors: list[str] = []
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Unable to load {CONFIG_PATH.name}: {error}")
        return 1

    rules = config.get("headers")
    if not isinstance(rules, list):
        errors.append("vercel.json must define a headers array")
        rules = []
    matching = [rule for rule in rules if isinstance(rule, dict) and rule.get("source") == "/(.*)"]
    if len(matching) != 1:
        errors.append("vercel.json must have exactly one global /(.*) header rule")
        header_rows: list[object] = []
    else:
        header_rows = matching[0].get("headers", [])

    headers: dict[str, str] = {}
    if not isinstance(header_rows, list):
        errors.append("global Vercel header rule must contain a headers array")
        header_rows = []
    for row in header_rows:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not isinstance(row.get("value"), str):
            errors.append("each Vercel header must contain string key/value fields")
            continue
        key = row["key"].lower()
        if key in headers:
            errors.append(f"duplicate Vercel header: {row['key']}")
        headers[key] = row["value"]

    missing = sorted(REQUIRED_HEADERS - headers.keys())
    if missing:
        errors.append(f"missing required security headers: {', '.join(missing)}")

    csp = parse_csp(headers.get("content-security-policy", ""))
    for directive, required_values in REQUIRED_CSP.items():
        actual = csp.get(directive, set())
        if not required_values.issubset(actual):
            errors.append(
                f"CSP {directive} must contain {', '.join(sorted(required_values))}; got {sorted(actual)}"
            )
    connect_sources = csp.get("connect-src", set())
    missing_connect = sorted(REQUIRED_CONNECT_SOURCES - connect_sources)
    if missing_connect:
        errors.append(f"CSP connect-src is missing: {', '.join(missing_connect)}")
    csp_text = headers.get("content-security-policy", "")
    for forbidden in ("'unsafe-inline'", "'unsafe-eval'", "*"):
        if forbidden in csp_text.split():
            errors.append(f"CSP contains forbidden source expression: {forbidden}")

    if headers.get("x-content-type-options", "").lower() != "nosniff":
        errors.append("X-Content-Type-Options must be nosniff")
    if headers.get("x-frame-options", "").upper() != "DENY":
        errors.append("X-Frame-Options must be DENY")
    if headers.get("cross-origin-opener-policy", "").lower() != "same-origin":
        errors.append("Cross-Origin-Opener-Policy must be same-origin")

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for label, pattern in INLINE_HTML_PATTERNS.items():
        if pattern.search(html):
            errors.append(f"index.html contains CSP-incompatible {label}")

    for path in sorted((ROOT / "src").rglob("*.js")):
        if "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if DYNAMIC_STYLE_PATTERN.search(text):
            errors.append(f"{path.relative_to(ROOT)} contains dynamic inline style mutation")
        if UNSAFE_SCRIPT_PATTERN.search(text):
            errors.append(f"{path.relative_to(ROOT)} contains eval/new Function")

    if errors:
        print("\n".join(errors))
        return 1
    print("Vercel security-header and strict-CSP compatibility checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
