"""Current TPEX common-stock identity snapshot for research-only features."""

from __future__ import annotations

from .current_identity_repository import (
    CurrentIdentityRepository,
    SecurityRowSource,
)


class TpexCurrentIdentityRepository(CurrentIdentityRepository):
    def __init__(self, source: SecurityRowSource, *, page_size: int = 500) -> None:
        super().__init__(source, market="TPEX", page_size=page_size)


__all__ = ["TpexCurrentIdentityRepository"]
