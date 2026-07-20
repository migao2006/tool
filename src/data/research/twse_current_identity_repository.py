"""Backward-compatible TWSE identity repository entry point."""

from .current_identity_repository import CurrentIdentityRepository, SecurityRowSource


class TwseCurrentIdentityRepository(CurrentIdentityRepository):
    def __init__(self, source: SecurityRowSource, *, page_size: int = 500) -> None:
        super().__init__(source, market="TWSE", page_size=page_size)


__all__ = ["SecurityRowSource", "TwseCurrentIdentityRepository"]
