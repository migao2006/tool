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


def test_prediction_client_accepts_horizon_fetches_only_when_configured() -> None:
    contract = read("src/core/five-day-contract.js")
    client = read("src/data/prediction-api.js")
    transport = read("src/data/api-client.js")
    public_config = read("src/core/public-config.js")
    assert "CURRENT_HORIZON = 5" in contract
    assert "horizon = CURRENT_HORIZON" in client
    assert "normalizeHorizon(horizon)" in client
    assert "PREDICTION_API_NOT_CONFIGURED" in client
    assert "predictionApiBaseUrl" in transport
    assert "config.predictionApiBaseUrl" in transport
    assert "PREDICTION_API_TIMEOUT" in transport
    assert "PREDICTION_API_NETWORK_ERROR" in transport
    assert "PREDICTION_API_VERSION_CONFLICT" in transport
    assert "PREDICTION_API_RATE_LIMITED" in transport
    assert "PREDICTION_API_INVALID_JSON" in transport
    assert 'cache: "no-store"' in transport
    assert 'predictionApiContractVersion: "prediction-snapshot.v1"' in public_config
    assert 'new URL("./", globalThis.location.href)' in public_config
    assert "new URL(apiBaseUrl, globalThis.location?.href)" in transport
    assert "fetch(url" in transport
    assert "query: predictionQuery(normalizedHorizon, settings)" in client
    assert "readSupabaseAccessToken" in client
    assert "accessToken," in client
    assert "PREDICTION_API_CONTRACT_ERROR" in client


def test_watchlist_api_requires_session_and_refreshes_after_auth_changes() -> None:
    app = read("app.js")
    watchlist = read("src/data/watchlist-api.js")
    stock = read("src/pages/stock-detail-page.js")
    auth_controller = read("src/auth/auth-controller.js")

    assert "data-toggle-watchlist" in stock
    assert "readSupabaseAccessToken" in watchlist
    assert 'method: selected ? "PUT" : "DELETE"' in watchlist
    assert "WATCHLIST_AUTH_REQUIRED" in watchlist
    assert 'addEventListener("alpha-lens:auth-change"' in app
    assert 'new CustomEvent("alpha-lens:auth-change"' in auth_controller


def test_supabase_sdk_loader_is_shared_bounded_and_fail_closed() -> None:
    index = read("index.html")
    loader = read("src/data/supabase-sdk-loader.js")
    client = read("src/data/supabase-client.js")
    prediction = read("src/data/prediction-api.js")

    assert "supabase-2.110.7.min.js" not in index
    assert "let sdkPromise" in loader
    assert "MAX_ATTEMPTS = 2" in loader
    assert "SUPABASE_SDK_LOAD_FAILED" in loader
    assert "sdkPromise ??= loadWithRetry()" in loader
    assert "await loadSupabaseCreateClient()" in client
    assert "isSupabaseSdkLoadError(error)" in prediction


def test_decision_gate_renderer_matches_backend_contract_and_formats_objects() -> None:
    gates = read("src/components/decision-gates.js")
    for key in (
        "data_quality_hard_gate",
        "tradability_gate",
        "liquidity_capacity_gate",
        "market_exposure_cap",
        "calibrated_direction_probabilities",
        "net_quantile_thresholds",
        "rank_eligibility",
        "position_capacity_limits",
    ):
        assert key in gates
    assert "JSON.stringify(value)" in gates


def test_stock_route_and_saved_research_settings_are_guarded() -> None:
    app = read("app.js")
    router = read("src/core/router.js")
    settings = read("src/features/research-settings.js")
    form = read("src/components/research-settings-drawer.js")

    assert 'canActivate: (route) => route !== "stock" || Boolean(selectedSymbol)' in app
    assert 'router.current() === "stock"' in app
    assert "canActivate(requestedRoute)" in router
    assert "history.replaceState" in router
    assert "NUMERIC_RULES" in settings
    assert "COST_PROFILES" in settings
    assert "請修正超出允許範圍的設定" in settings
    assert 'min="0.01" max="1"' in form
    assert 'name="estimated_order_notional_ntd" type="number" min="1"' in form


def test_drawer_restores_focus_to_its_opening_control() -> None:
    drawer = read("src/components/drawer-controller.js")
    assert "drawerTriggers = new WeakMap()" in drawer
    assert "drawerTriggers.set(drawer, trigger)" in drawer
    assert "drawerTriggers.get(drawer)?.focus()" in drawer


def test_prediction_schema_rejects_wrong_horizon_and_invalid_formal_output() -> None:
    contract = read("src/data/prediction-contract.js") + read("src/data/prediction-validator.js")
    assert "目前只接受 5 個交易日模型輸出" in contract
    assert "horizon 與請求不一致" in contract
    assert "機率總和不等於 1" in contract
    assert "淨報酬分位數不完整或不單調" in contract
    assert "PASS 快照缺少有效日期或模型版本稽核欄位" in contract
    assert "API 契約版本" in contract
    assert '["market_direction", "direction"], raw' in contract
    assert "使用了決策時間之後的資料" in contract
    assert "決策 gate 缺漏或順序錯誤" in contract
    assert 'market_regime: nullableString(firstValue(record' in contract


def test_forbidden_unverified_outputs_are_absent_from_stock_page() -> None:
    stock = read("src/pages/stock-detail-page.js")
    for forbidden in ("Alpha Score", "預期報酬", "MFE", "MAE", "final score"):
        assert forbidden not in stock
    assert "當日橫斷面排名百分位" in stock
    assert "條件報酬分位數" in stock


def test_formal_candidates_exclude_hard_fail_and_etf() -> None:
    selection = read("src/features/prediction-selection.js")
    candidates = read("src/pages/candidates-page.js")
    assert 'record.asset_type !== "ETF"' in selection
    assert "!record.data_quality_hard_fail" in selection
    assert "renderExcludedSecurities(snapshot.excluded)" in candidates
    assert '<option>FAIL</option>' not in candidates


def test_api_values_are_escaped_before_dynamic_markup() -> None:
    html = read("src/core/html.js")
    card = read("src/components/candidate-card.js")
    excluded = read("src/components/excluded-securities-drawer.js")
    assert "escapeHtml" in html
    assert "escapeHtml(prediction.symbol" in card
    assert "map(escapeHtml)" in card
    assert "map(escapeHtml)" in excluded


def test_no_embedded_fake_stock_or_performance_data() -> None:
    frontend = "\n".join(
        read(path)
        for path in (
            "app.js",
            "src/pages/overview-page.js",
            "src/pages/candidates-page.js",
            "src/pages/stock-detail-page.js",
            "src/pages/watchlist-page.js",
        )
    )
    for forbidden in ("2330", "台積電", "2317", "鴻海", "Sharpe 1", "年化報酬"):
        assert forbidden not in frontend


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
