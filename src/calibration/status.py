"""Shared production calibration-status contract."""

from __future__ import annotations

from typing import Any


UNUSABLE_CALIBRATION_VERSIONS = frozenset(
    {
        "",
        "-",
        "—",
        "NONE",
        "NOT-TRAINED",
        "NOT_TRAINED",
        "RESEARCH_ONLY",
        "UNCALIBRATED",
    }
)


def has_usable_version(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().upper() not in UNUSABLE_CALIBRATION_VERSIONS


def has_valid_calibration_version(value: Any) -> bool:
    return has_usable_version(value)


def has_calibrated_interval_status(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    prefix, separator, version = value.strip().partition(":")
    return (
        separator == ":"
        and prefix.upper() == "CALIBRATED"
        and has_usable_version(version)
    )
