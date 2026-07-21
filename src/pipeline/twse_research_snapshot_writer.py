"""Atomic JSON persistence shared by OOS and daily research snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import cast
from uuid import uuid4

from .twse_research_prediction_contracts import TwseResearchPredictionSnapshot


@dataclass(frozen=True)
class PersistedResearchSnapshot:
    path: Path
    artifact_sha256: str
    snapshot: TwseResearchPredictionSnapshot


def persist_research_snapshot(
    path: Path,
    snapshot: TwseResearchPredictionSnapshot,
) -> PersistedResearchSnapshot:
    """Write only a contract-valid snapshot and verify immutable read-back."""

    payload = snapshot.to_dict()
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.partial")
    try:
        _ = temporary.write_bytes(rendered)
        read_back = temporary.read_bytes()
        if read_back != rendered:
            raise OSError("research prediction artifact read-back mismatch")
        decoded = cast(
            dict[str, object], json.loads(read_back.decode("utf-8"))
        )
        if decoded.get("snapshot_sha256") != snapshot.snapshot_sha256:
            raise OSError("research prediction snapshot hash mismatch")
        _ = temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_bytes = path.read_bytes()
    if artifact_bytes != rendered:
        raise OSError("persisted research prediction artifact changed")
    return PersistedResearchSnapshot(
        path=path,
        artifact_sha256=sha256(artifact_bytes).hexdigest(),
        snapshot=snapshot,
    )


__all__ = ["PersistedResearchSnapshot", "persist_research_snapshot"]
