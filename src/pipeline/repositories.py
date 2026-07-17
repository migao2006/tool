"""Real-data repositories used by pipeline commands."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

from .contracts import DatasetRepository, PipelineBatch, PipelineMode


class DataSourceError(RuntimeError):
    """Raised when real input cannot be read without making assumptions."""


class FileDatasetRepository:
    """Read a CSV or Parquet snapshot without filling or synthesizing rows."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(
        self,
        *,
        mode: PipelineMode,
        horizon: int,
        as_of_date: date | None,
    ) -> PipelineBatch:
        del mode, horizon, as_of_date
        if not self.path.is_file():
            raise DataSourceError(f"input file does not exist: {self.path}")
        if self.path.stat().st_size == 0:
            raise DataSourceError(f"input file is empty: {self.path}")
        try:
            import pandas as pd
        except ModuleNotFoundError as error:
            raise DataSourceError("pandas is required to read pipeline input") from error

        suffix = self.path.suffix.lower()
        try:
            if suffix == ".csv":
                frame = pd.read_csv(self.path)
            elif suffix in {".parquet", ".pq"}:
                frame = pd.read_parquet(self.path)
            else:
                raise DataSourceError("only .csv, .parquet, and .pq inputs are supported")
        except DataSourceError:
            raise
        except Exception as error:
            raise DataSourceError(f"cannot read {self.path}: {error}") from error
        return PipelineBatch(
            records=frame,
            source_uri=self.path.resolve().as_uri(),
            source_hash=sha256(self.path.read_bytes()).hexdigest(),
        )


def load_object(reference: str) -> Any:
    """Load ``module:attribute`` without constraining repository implementation."""

    module_name, separator, attribute_name = reference.partition(":")
    if not separator or not module_name or not attribute_name:
        raise DataSourceError("object reference must use module:attribute syntax")
    try:
        value = getattr(import_module(module_name), attribute_name)
    except (ImportError, AttributeError) as error:
        raise DataSourceError(f"cannot load object reference {reference}: {error}") from error
    return value() if isinstance(value, type) else value


def repository_from_reference(reference: str) -> DatasetRepository:
    repository = load_object(reference)
    if not isinstance(repository, DatasetRepository):
        raise DataSourceError(f"{reference} does not implement DatasetRepository.load")
    return repository
