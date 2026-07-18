"""Provider-neutral payload and readiness contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class ProviderPayload:
    """Raw JSON plus immutable provenance; normalization happens downstream."""

    provider: str
    dataset: str
    source_version: str
    source_url: str
    retrieved_at: datetime
    payload_sha256: str
    payload: Any = field(repr=False)
    request_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider or not self.dataset or not self.source_version:
            raise ValueError("provider, dataset, and source_version are required")
        if not self.source_url.startswith("https://"):
            raise ValueError("provider source_url must use HTTPS")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be a SHA-256 hex digest")

    @property
    def record_count(self) -> int | None:
        """Best-effort count without pretending every provider has one schema."""

        if isinstance(self.payload, list):
            return len(self.payload)
        if not isinstance(self.payload, dict):
            return None
        for key in ("data", "values", "observations"):
            value = self.payload.get(key)
            if isinstance(value, list):
                return len(value)
        nested_data = self.payload.get("data")
        if isinstance(nested_data, dict) and isinstance(nested_data.get("dataSets"), list):
            return len(nested_data["dataSets"])
        return None

    def to_dict(self, *, include_payload: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": self.provider,
            "dataset": self.dataset,
            "source_version": self.source_version,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at.isoformat(),
            "payload_sha256": self.payload_sha256,
            "record_count": self.record_count,
            "request_metadata": dict(self.request_metadata),
        }
        if include_payload:
            result["payload"] = self.payload
        return result


@dataclass(frozen=True)
class ProviderReadiness:
    provider: str
    configured: bool
    credential_environment_variables: tuple[str, ...]
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.configured and self.reason_code is not None:
            raise ValueError("configured provider cannot have a failure reason")
        if not self.configured and not self.reason_code:
            raise ValueError("unconfigured provider requires a reason code")
