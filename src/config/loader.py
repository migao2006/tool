from __future__ import annotations

from pathlib import Path
import tomllib

from .types import (
    CostConfig,
    DecisionConfig,
    MvpConfig,
    PortfolioConfig,
    RankConfig,
    ValidationConfig,
)


DEFAULT_CONFIG_PATH = Path("config/five_day_mvp.toml")


def load_mvp_config(path: str | Path = DEFAULT_CONFIG_PATH) -> MvpConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    return MvpConfig(
        horizon=int(raw["mvp"]["horizon"]),
        status=str(raw["mvp"]["status"]),
        listed_benchmark=str(raw["benchmarks"]["listed"]),
        otc_benchmark=str(raw["benchmarks"]["otc"]),
        cost=CostConfig(**raw["cost"]),
        rank=RankConfig(
            **{key: value for key, value in raw["rank"].items() if key != "eval_at"},
            eval_at=tuple(int(value) for value in raw["rank"]["eval_at"]),
        ),
        decision=DecisionConfig(**raw["decision"]),
        portfolio=PortfolioConfig(**raw["portfolio"]),
        validation=ValidationConfig(**raw["validation"]),
        feature_available_at_policy=str(raw["data"]["available_at_policy"]),
        extra={key: value for key, value in raw.items() if key not in {
            "mvp", "benchmarks", "cost", "rank", "decision", "portfolio",
            "validation", "data",
        }},
    )
