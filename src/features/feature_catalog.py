from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


DEFAULT_FEATURE_CATALOG = Path("config/feature_catalog.json")


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    formula: str
    source: str
    available_at_rule: str
    missing_policy: str


def load_feature_catalog(
    path: str | Path = DEFAULT_FEATURE_CATALOG,
) -> tuple[FeatureDefinition, ...]:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    definitions = tuple(FeatureDefinition(**item) for item in raw)
    names = [item.name for item in definitions]
    if len(names) != len(set(names)):
        raise ValueError("Feature catalog contains duplicate feature names")
    return definitions

