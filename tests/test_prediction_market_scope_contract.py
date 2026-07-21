import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_edge_function_requires_an_exact_market_scope() -> None:
    handler = read("supabase/functions/prediction-snapshot/handler.ts")
    repository = read("supabase/functions/prediction-snapshot/repository.ts")
    snapshot = read("supabase/functions/prediction-snapshot/snapshot.ts")
    types = read("supabase/functions/prediction-snapshot/types.ts")

    assert 'marketValues.length === 0 ? "TWSE"' in handler
    assert 'market !== "TWSE" && market !== "TPEX"' in handler
    assert '"UNSUPPORTED_MARKET"' in handler
    assert re.search(
        r"loadLatest\(\s*query\.horizon,\s*query\.marketScope,"
        r"\s*signal,\s*observedAt,\s*\)",
        handler,
    )
    assert "market_scope: `eq.${marketScope}`" in repository
    assert "market_scope: MarketScope | null" in types
    assert 'rows.run.market_scope ?? "TWSE"' in snapshot
    assert '"PREDICTION_MARKET_SCOPE_MISMATCH"' in snapshot
    assert "market_scope: marketScope" in snapshot


def test_frontend_keeps_market_snapshots_and_stock_identity_separate() -> None:
    app = read("app.js")
    client = read("src/data/prediction-api.js")
    contract = read("src/data/prediction-contract.js")
    card = read("src/components/candidate-card.js")
    router = read("src/core/router.js")

    assert "const snapshots = new Map()" in app
    assert "const snapshotStates = new Map()" in app
    assert "requestControllers.get(market)?.abort()" in app
    assert "market = DEFAULT_MARKET_SCOPE" in client
    assert "return { horizon, market: marketScope }" in client
    assert "marketScope !== requestedMarketScope" in contract
    assert "record.market !== marketScope" in contract
    assert 'data-stock-key="${stockKey}"' in card
    assert 'data-market="${market}"' in card
    assert "stockRoutePath(targetStockKey)" in router


def test_market_switch_has_only_listed_and_otc_datasets() -> None:
    market_switch = read("src/components/market-scope-switch.js")
    candidates = read("src/pages/candidates-page.js")

    assert 'data-market-scope="TWSE"' in market_switch
    assert 'data-market-scope="TPEX"' in market_switch
    assert 'data-market-scope="ALL"' not in market_switch
    assert 'data-filter="market"' not in candidates
    assert "ETF" not in market_switch
