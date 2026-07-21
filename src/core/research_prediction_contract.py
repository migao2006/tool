"""Stable identifier shared by research artifact producers and adapters."""

RESEARCH_PREDICTION_CONTRACT_VERSION = "twse-research-prediction-snapshot.v1"
TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION = "tpex-research-prediction-snapshot.v1"


def research_prediction_contract_version(market: str) -> str:
    normalized = market.strip().upper()
    if normalized == "TWSE":
        return RESEARCH_PREDICTION_CONTRACT_VERSION
    if normalized == "TPEX":
        return TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION
    raise ValueError("research prediction market is unsupported")


__all__ = [
    "RESEARCH_PREDICTION_CONTRACT_VERSION",
    "TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION",
    "research_prediction_contract_version",
]
