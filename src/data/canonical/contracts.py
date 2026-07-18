"""Immutable, auditable contracts for historical daily-bar promotion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from collections.abc import Mapping

from ._contract_validation import MARKETS, TAIPEI, digest, required_text, utc


CANONICAL_DAILY_BAR_SCHEMA_VERSION = "canonical_daily_bar.v1"


@dataclass(frozen=True)
class CanonicalDailyBar:
    """One canonical research row with immutable raw and identity lineage."""

    schema_version: str
    listing_period_id: str
    security_id: int
    market: str
    symbol: str
    trade_date: date
    decision_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    trading_volume: Decimal | None
    trading_value: Decimal | None
    trade_count: int | None
    raw_archive_key: str
    raw_object_key: str
    raw_parquet_sha256: str
    raw_source_revision_hash: str
    raw_source_payload_hash: str
    raw_first_observed_at: datetime
    raw_available_at: datetime
    raw_available_at_basis: str
    identity_revision_hash: str
    publication_rule_version: str
    calendar_revision_hash: str | None
    calendar_available_at: datetime | None
    company_action_revision_hash: str | None
    company_action_available_at: datetime | None
    point_in_time_status: str
    usage_scope: str
    system_status: str
    production_eligible: bool
    reason_codes: tuple[str, ...]
    canonical_row_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != CANONICAL_DAILY_BAR_SCHEMA_VERSION:
            raise ValueError("unsupported canonical schema version")
        if self.market not in MARKETS or self.security_id <= 0:
            raise ValueError("canonical identity is invalid")
        object.__setattr__(self, "decision_at", utc(self.decision_at, "decision_at"))
        if self.trade_date != self.decision_at.astimezone(TAIPEI).date():
            raise ValueError("canonical trade date differs from Taipei decision date")
        if not self.listing_period_id.strip() or not self.symbol.strip():
            raise ValueError("canonical listing identity is required")
        object.__setattr__(
            self,
            "raw_object_key",
            required_text(self.raw_object_key, "raw_object_key"),
        )
        object.__setattr__(
            self,
            "raw_first_observed_at",
            utc(self.raw_first_observed_at, "raw_first_observed_at"),
        )
        object.__setattr__(
            self, "raw_available_at", utc(self.raw_available_at, "raw_available_at")
        )
        if self.raw_available_at_basis not in {
            "OFFICIAL_PUBLICATION_AT",
            "VERSIONED_SNAPSHOT",
            "FIRST_OBSERVED_AT_RETRIEVAL",
        }:
            raise ValueError("unsupported raw_available_at_basis")
        if self.raw_available_at_basis == "OFFICIAL_PUBLICATION_AT":
            if self.raw_available_at > self.raw_first_observed_at:
                raise ValueError("raw availability follows first observation")
        elif self.raw_available_at != self.raw_first_observed_at:
            raise ValueError("raw snapshot availability must equal first observation")
        object.__setattr__(
            self,
            "publication_rule_version",
            required_text(self.publication_rule_version, "publication_rule_version"),
        )
        if self.calendar_available_at is not None:
            object.__setattr__(
                self,
                "calendar_available_at",
                utc(self.calendar_available_at, "calendar_available_at"),
            )
        if self.company_action_available_at is not None:
            object.__setattr__(
                self,
                "company_action_available_at",
                utc(
                    self.company_action_available_at,
                    "company_action_available_at",
                ),
            )
        object.__setattr__(
            self, "raw_archive_key", digest(self.raw_archive_key, "raw_archive_key")
        )
        object.__setattr__(
            self,
            "raw_parquet_sha256",
            digest(self.raw_parquet_sha256, "raw_parquet_sha256"),
        )
        object.__setattr__(
            self,
            "raw_source_revision_hash",
            digest(self.raw_source_revision_hash, "raw_source_revision_hash"),
        )
        object.__setattr__(
            self,
            "raw_source_payload_hash",
            digest(self.raw_source_payload_hash, "raw_source_payload_hash"),
        )
        object.__setattr__(
            self,
            "identity_revision_hash",
            digest(self.identity_revision_hash, "identity_revision_hash"),
        )
        if self.calendar_revision_hash is not None:
            object.__setattr__(
                self,
                "calendar_revision_hash",
                digest(self.calendar_revision_hash, "calendar_revision_hash"),
            )
        if self.company_action_revision_hash is not None:
            object.__setattr__(
                self,
                "company_action_revision_hash",
                digest(
                    self.company_action_revision_hash,
                    "company_action_revision_hash",
                ),
            )
        object.__setattr__(
            self,
            "canonical_row_hash",
            digest(self.canonical_row_hash, "canonical_row_hash"),
        )
        if min(self.open_price, self.high_price, self.low_price, self.close_price) <= 0:
            raise ValueError("canonical OHLC prices must be positive")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("canonical low price exceeds open or close")
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("canonical high price is below open or close")
        if self.low_price > self.high_price:
            raise ValueError("canonical low price exceeds high price")
        if self.trading_volume is not None and self.trading_volume < 0:
            raise ValueError("canonical trading volume cannot be negative")
        if self.trading_value is not None and self.trading_value < 0:
            raise ValueError("canonical trading value cannot be negative")
        if self.trade_count is not None and self.trade_count < 0:
            raise ValueError("canonical trade count cannot be negative")
        if self.point_in_time_status not in {"VERIFIED", "UNVERIFIED"}:
            raise ValueError("unsupported canonical point_in_time_status")
        if self.usage_scope not in {"MODEL_ELIGIBLE", "RESEARCH_ONLY"}:
            raise ValueError("unsupported canonical usage_scope")
        if self.system_status not in {"PASS", "RESEARCH_ONLY", "FAIL"}:
            raise ValueError("unsupported canonical system_status")
        if self.production_eligible:
            if (
                self.point_in_time_status != "VERIFIED"
                or self.usage_scope != "MODEL_ELIGIBLE"
                or self.system_status != "PASS"
                or self.reason_codes
                or self.raw_available_at > self.decision_at
                or self.raw_available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL"
                or self.calendar_revision_hash is None
                or self.calendar_available_at is None
                or self.calendar_available_at > self.decision_at
                or self.company_action_revision_hash is None
                or self.company_action_available_at is None
                or self.company_action_available_at > self.decision_at
            ):
                raise ValueError("production-eligible row exceeds verified evidence")
        elif self.system_status == "PASS" or not self.reason_codes:
            raise ValueError("ineligible row must remain non-PASS with reasons")

    @staticmethod
    def content_hash(values: Mapping[str, object]) -> str:
        def serialize(value: object) -> str:
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            if isinstance(value, Decimal):
                return str(value)
            return str(value)

        canonical = json.dumps(
            values,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=serialize,
        ).encode("utf-8")
        return sha256(canonical).hexdigest()


@dataclass(frozen=True)
class PromotionResult:
    """Batch result that never hides exclusions or research-only rows."""

    source_row_count: int
    canonical_rows: tuple[CanonicalDailyBar, ...]
    rejected_row_count: int
    reason_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.source_row_count != len(self.canonical_rows) + self.rejected_row_count:
            raise ValueError("promotion accounting does not match source rows")

    @property
    def production_eligible_count(self) -> int:
        return sum(row.production_eligible for row in self.canonical_rows)
