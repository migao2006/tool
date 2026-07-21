"""Backward-compatible TWSE import path for shared record adapters."""

from .price_volume_record_adapter import (
    MISSING,
    available_at_basis,
    date_value,
    market_value,
    materialize_records,
    observed_available_at,
    optional_number,
    read_field,
    required_text,
    source_reason_codes,
)

__all__ = [
    "MISSING",
    "available_at_basis",
    "date_value",
    "market_value",
    "materialize_records",
    "observed_available_at",
    "optional_number",
    "read_field",
    "required_text",
    "source_reason_codes",
]
