from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_index_is_a_shell_and_pages_are_modular() -> None:
    index = read("index.html")
    app = read("app.js")

    assert 'id="app-content"' in index
    assert "data-page=" not in index
    for module in (
        "overview-page.js",
        "candidates-page.js",
        "stock-detail-page.js",
        "watchlist-page.js",
    ):
        assert module in app


def test_only_five_day_controls_are_exposed() -> None:
    pages = "\n".join(
        read(path)
        for path in (
            "src/pages/overview-page.js",
            "src/pages/candidates-page.js",
            "src/pages/stock-detail-page.js",
            "src/pages/watchlist-page.js",
        )
    )
    assert 'data-horizon="${horizon}"' in pages
    assert not re.search(r">\s*(2|3|10)\s*日\s*<", pages)
    assert 'data-value="etf"' not in pages.lower()
    assert "我的持倉" not in pages


def test_bottom_navigation_has_exactly_three_product_entries() -> None:
    navigation = read("src/components/bottom-navigation.js")
    assert navigation.count("{ route:") == 3
    assert 'label: "總覽"' in navigation
    assert 'label: "5 日候選"' in navigation
    assert 'label: "自選"' in navigation


def test_prediction_client_accepts_horizon_and_defaults_to_five() -> None:
    contract = read("src/core/five-day-contract.js")
    client = read("src/data/prediction-api.js")
    assert "CURRENT_HORIZON = 5" in contract
    assert "horizon = CURRENT_HORIZON" in client
    assert "normalizeHorizon(horizon)" in client
    assert "fetch(" not in client


def test_forbidden_unverified_outputs_are_absent_from_stock_page() -> None:
    stock = read("src/pages/stock-detail-page.js")
    for forbidden in ("Alpha Score", "預期報酬", "MFE", "MAE", "final score"):
        assert forbidden not in stock
    assert "Rank Score（當日橫斷面排名百分位）" in stock
    assert "條件報酬分位數" in stock


def test_all_required_ui_states_have_copy() -> None:
    ui_state = read("src/core/ui-state.js")
    for state in (
        "LOADING",
        "EMPTY",
        "STALE",
        "DATA_QUALITY_HARD_FAIL",
        "API_ERROR",
        "RESEARCH_ONLY",
        "FAIL",
        "MODEL_NOT_AVAILABLE",
        "NO_CANDIDATES",
    ):
        assert state in ui_state
