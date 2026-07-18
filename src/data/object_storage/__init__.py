"""Object-storage adapters used by data ingestion and archival workflows."""

from src.data.object_storage.r2_client import (
    ObjectMetadata,
    R2Client,
    R2ConfigurationError,
    R2Settings,
)

__all__ = [
    "ObjectMetadata",
    "R2Client",
    "R2ConfigurationError",
    "R2Settings",
]
