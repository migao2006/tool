"""Historical identity, decision-cutoff, and coverage evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ._contract_validation import MARKETS, TAIPEI, digest, required_text, utc


@dataclass(frozen=True)
class ListingPeriodIdentity:
    """One independently sourced listing episode, never a current-symbol guess."""

    listing_period_id: str
    security_id: int | None
    isin: str | None
    market: str
    source_symbol: str
    asset_type: str
    effective_from: date
    effective_to: date | None
    available_at: datetime
    first_observed_at: datetime
    source_id: int
    source_dataset: str
    source_version: str
    source_revision_hash: str
    source_payload_hash: str
    resolution_status: str
    available_at_basis: str
    point_in_time_status: str
    usage_scope: str
    system_status: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "listing_period_id",
            required_text(self.listing_period_id, "listing_period_id"),
        )
        if self.security_id is not None and self.security_id <= 0:
            raise ValueError("security_id must be positive when provided")
        if self.isin is not None and (
            len(self.isin) != 12
            or not self.isin.isalnum()
            or self.isin != self.isin.upper()
        ):
            raise ValueError("isin must be a 12-character uppercase identifier")
        if self.market not in MARKETS:
            raise ValueError("market must be TWSE or TPEX")
        object.__setattr__(
            self,
            "source_symbol",
            required_text(self.source_symbol, "source_symbol"),
        )
        if self.asset_type != "COMMON_STOCK":
            raise ValueError("only common-stock identities are supported")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        object.__setattr__(self, "available_at", utc(self.available_at, "available_at"))
        object.__setattr__(
            self,
            "first_observed_at",
            utc(self.first_observed_at, "first_observed_at"),
        )
        if self.source_id <= 0:
            raise ValueError("source_id must be positive")
        object.__setattr__(
            self,
            "source_dataset",
            required_text(self.source_dataset, "source_dataset"),
        )
        object.__setattr__(
            self,
            "source_version",
            required_text(self.source_version, "source_version"),
        )
        object.__setattr__(
            self,
            "source_revision_hash",
            digest(self.source_revision_hash, "source_revision_hash"),
        )
        object.__setattr__(
            self,
            "source_payload_hash",
            digest(self.source_payload_hash, "source_payload_hash"),
        )
        if self.resolution_status not in {"VERIFIED", "UNRESOLVED", "CONFLICT"}:
            raise ValueError("unsupported resolution_status")
        available_at_basis = required_text(
            self.available_at_basis, "available_at_basis"
        )
        if available_at_basis not in {
            "OFFICIAL_PUBLICATION_AT",
            "VERSIONED_SNAPSHOT",
            "FIRST_OBSERVED_AT_RETRIEVAL",
        }:
            raise ValueError("unsupported available_at_basis")
        object.__setattr__(self, "available_at_basis", available_at_basis)
        if available_at_basis == "OFFICIAL_PUBLICATION_AT":
            if self.available_at > self.first_observed_at:
                raise ValueError(
                    "official availability cannot follow first observation"
                )
        elif self.available_at != self.first_observed_at:
            raise ValueError(
                "snapshot availability must equal the first observation time"
            )
        if self.point_in_time_status not in {"VERIFIED", "UNVERIFIED"}:
            raise ValueError("unsupported point_in_time_status")
        if self.usage_scope not in {
            "POINT_IN_TIME_IDENTITY",
            "IDENTITY_RESEARCH_ONLY",
        }:
            raise ValueError("unsupported identity usage_scope")
        if self.system_status not in {"PASS", "RESEARCH_ONLY", "FAIL"}:
            raise ValueError("unsupported identity system_status")
        if self.system_status == "PASS" and (
            self.resolution_status != "VERIFIED"
            or self.security_id is None
            or self.isin is None
            or available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL"
            or self.point_in_time_status != "VERIFIED"
            or self.usage_scope != "POINT_IN_TIME_IDENTITY"
            or self.reason_codes
        ):
            raise ValueError("PASS identity exceeds verified evidence")
        if self.system_status != "PASS" and (
            self.resolution_status not in {"UNRESOLVED", "CONFLICT"}
            or self.security_id is not None
            or self.usage_scope != "IDENTITY_RESEARCH_ONLY"
            or not self.reason_codes
        ):
            raise ValueError(
                "non-PASS identity must remain unresolved research evidence"
            )

    def covers(self, trade_date: date) -> bool:
        return self.effective_from <= trade_date and (
            self.effective_to is None or trade_date < self.effective_to
        )


@dataclass(frozen=True)
class HistoricalDecisionContext:
    """Externally verified decision cutoff and coverage for one market session."""

    market: str
    trade_date: date
    decision_at: datetime
    publication_rule_version: str
    calendar_revision_hash: str | None
    calendar_available_at: datetime | None
    calendar_status: str
    company_action_coverage_status: str
    company_action_revision_hash: str | None
    company_action_available_at: datetime | None

    def __post_init__(self) -> None:
        if self.market not in MARKETS:
            raise ValueError("market must be TWSE or TPEX")
        object.__setattr__(self, "decision_at", utc(self.decision_at, "decision_at"))
        if self.decision_at.astimezone(TAIPEI).date() != self.trade_date:
            raise ValueError("decision_at does not belong to the Taipei trade date")
        object.__setattr__(
            self,
            "publication_rule_version",
            required_text(self.publication_rule_version, "publication_rule_version"),
        )
        if self.calendar_revision_hash is not None:
            object.__setattr__(
                self,
                "calendar_revision_hash",
                digest(self.calendar_revision_hash, "calendar_revision_hash"),
            )
        if self.calendar_available_at is not None:
            object.__setattr__(
                self,
                "calendar_available_at",
                utc(self.calendar_available_at, "calendar_available_at"),
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
        if self.company_action_available_at is not None:
            object.__setattr__(
                self,
                "company_action_available_at",
                utc(
                    self.company_action_available_at,
                    "company_action_available_at",
                ),
            )
        if self.calendar_status not in {"VERIFIED", "UNVERIFIED"}:
            raise ValueError("unsupported calendar_status")
        if self.company_action_coverage_status not in {"VERIFIED", "UNVERIFIED"}:
            raise ValueError("unsupported company_action_coverage_status")
        if self.calendar_status == "VERIFIED" and (
            self.calendar_revision_hash is None
            or self.calendar_available_at is None
            or self.calendar_available_at > self.decision_at
        ):
            raise ValueError("verified calendar requires timely revision evidence")
        if self.company_action_coverage_status == "VERIFIED" and (
            self.company_action_revision_hash is None
            or self.company_action_available_at is None
            or self.company_action_available_at > self.decision_at
        ):
            raise ValueError(
                "verified company-action coverage requires timely revision evidence"
            )
