import { createBottomNavigation } from "./src/components/bottom-navigation.js";
import { initializeDrawers } from "./src/components/drawer-controller.js?v=debug-1";
import { initializeMarketScopeSwitches } from "./src/components/market-scope-switch.js?v=market-scope-1";
import { initializeResearchSettings } from "./src/features/research-settings.js?v=stored-snapshot-1";
import { initializeCandidateFilters } from "./src/features/candidate-filters.js?v=filter-sheet-1";
import { initializeWatchlistFilters } from "./src/features/watchlist-filters.js";
import { CURRENT_HORIZON } from "./src/core/five-day-contract.js";
import {
  DEFAULT_MARKET_SCOPE,
  createStockKey,
} from "./src/core/market-scope.js";
import { createRouter } from "./src/core/router.js?v=debug-2";
import {
  HOME_DATA_STATE,
  UI_STATE,
  applyUiState,
  resolveHomeDataState,
  resolveSnapshotUiState,
} from "./src/core/ui-state.js?v=research-ui-1";
import { renderHomeDataStatus } from "./src/components/home-data-status.js?v=mobile-ui-1";
import { loadHomeDataStatus } from "./src/data/home-data-status-api.js?v=home-data-2";
import { loadPredictionSnapshot } from "./src/data/prediction-api.js?v=market-scope-1";
import { createUnavailableSnapshot } from "./src/data/prediction-contract.js?v=market-scope-1";
import { setWatchlistMembership } from "./src/data/watchlist-api.js?v=market-scope-1";
import { isSupabaseSdkLoadError } from "./src/data/supabase-sdk-loader.js?v=auth-1";
import {
  createCandidatesPage,
  initializeCandidatePagination,
  renderCandidatesPage,
} from "./src/pages/candidates-page.js?v=filter-sheet-1";
import { createOverviewPage, renderOverviewPage } from "./src/pages/overview-page.js?v=market-scope-1";
import { createStockDetailPage, renderStockDetailPage } from "./src/pages/stock-detail-page.js?v=market-scope-1";
import { createWatchlistPage, renderWatchlistPage } from "./src/pages/watchlist-page.js?v=research-ui-1";

const appRoot = document.querySelector("#app-content");
const navigationRoot = document.querySelector("#navigation-root");

if (appRoot && navigationRoot) {
  appRoot.innerHTML = [
    createOverviewPage({ horizon: CURRENT_HORIZON }),
    createCandidatesPage({ horizon: CURRENT_HORIZON }),
    createStockDetailPage({ horizon: CURRENT_HORIZON }),
    createWatchlistPage({ horizon: CURRENT_HORIZON }),
  ].join("");
  navigationRoot.innerHTML = createBottomNavigation();

  const snapshots = new Map();
  const snapshotStates = new Map();
  const requestControllers = new Map();
  let selectedStockKey = null;
  let watchlistKeys = new Set();
  let marketSwitch = null;

  function findStock(stockKey) {
    const market = String(stockKey ?? "").split(":", 1)[0];
    const snapshot = snapshots.get(market);
    return [...(snapshot?.predictions ?? []), ...(snapshot?.watchlist ?? [])]
      .find((record) => createStockKey(record) === stockKey) ?? null;
  }

  const router = createRouter({
    canActivate: (route, routeState) => {
      if (route !== "stock") return true;
      const prediction = findStock(routeState.stockKey);
      if (!prediction) return false;
      selectedStockKey = routeState.stockKey;
      marketSwitch?.setActive(prediction.market);
      renderStockDetailPage(prediction, {
        isWatchlisted: watchlistKeys.has(selectedStockKey),
      });
      return true;
    },
  });
  const candidatePagination = initializeCandidatePagination({
    onChange: () => {
      const snapshot = snapshots.get(marketSwitch?.getActive());
      if (snapshot) {
        renderCandidatesPage(snapshot, snapshotStates.get(snapshot.marketScope), candidateFilters.getFilters());
      }
    },
  });
  const candidateFilters = initializeCandidateFilters({
    onChange: (filters) => {
      candidatePagination.reset();
      const snapshot = snapshots.get(marketSwitch?.getActive());
      if (snapshot) renderCandidatesPage(snapshot, snapshotStates.get(snapshot.marketScope), filters);
    },
  });
  const watchlistFilters = initializeWatchlistFilters({
    onChange: (decision) => {
      const snapshot = snapshots.get(marketSwitch?.getActive());
      if (snapshot) renderWatchlistPage(snapshot, decision);
    },
  });

  function renderSnapshot(snapshot, uiState) {
    watchlistKeys = new Set((snapshot.watchlist ?? []).map(createStockKey));
    candidateFilters.setRecords(snapshot.candidates ?? []);
    candidatePagination.reset();
    renderOverviewPage(snapshot, uiState);
    renderCandidatesPage(snapshot, uiState, candidateFilters.getFilters());
    renderWatchlistPage(snapshot, watchlistFilters.getDecision());
    if (selectedStockKey && router.current() === "stock") {
      const selected = findStock(selectedStockKey);
      if (selected) {
        renderStockDetailPage(selected, {
          isWatchlisted: watchlistKeys.has(selectedStockKey),
        });
      } else {
        selectedStockKey = null;
        router.show("opportunities");
      }
    }
  }

  function renderActiveMarket() {
    const market = marketSwitch?.getActive() ?? DEFAULT_MARKET_SCOPE;
    const snapshot = snapshots.get(market) ?? createUnavailableSnapshot({
      marketScope: market,
      reasonCode: "PREDICTION_SNAPSHOT_LOADING",
    });
    const uiState = snapshotStates.get(market) ?? UI_STATE.LOADING;
    applyUiState(uiState);
    renderSnapshot(snapshot, uiState);
  }

  async function refreshHomeDataStatus() {
    renderHomeDataStatus(null, HOME_DATA_STATE.LOADING);
    try {
      const status = await loadHomeDataStatus();
      renderHomeDataStatus(status, resolveHomeDataState({ status }));
    } catch (error) {
      renderHomeDataStatus(null, resolveHomeDataState({ error }), {
        reasonCode: error?.code,
      });
      if (!isSupabaseSdkLoadError(error)) globalThis.Sentry?.captureException?.(error);
    }
  }

  async function refreshSnapshot(market = marketSwitch?.getActive() ?? DEFAULT_MARKET_SCOPE) {
    requestControllers.get(market)?.abort();
    const requestController = new AbortController();
    requestControllers.set(market, requestController);
    snapshotStates.set(market, UI_STATE.LOADING);
    if (marketSwitch?.getActive() === market) renderActiveMarket();
    try {
      const snapshot = await loadPredictionSnapshot({
        horizon: CURRENT_HORIZON,
        market,
        signal: requestController.signal,
      });
      const uiState = resolveSnapshotUiState(snapshot);
      snapshots.set(market, snapshot);
      snapshotStates.set(market, uiState);
      if (marketSwitch?.getActive() === market) renderActiveMarket();
    } catch (error) {
      if (error?.name === "AbortError") return;
      const snapshot = createUnavailableSnapshot({
        marketScope: market,
        status: "FAIL",
        reasonCode: error?.code ?? "PREDICTION_API_REQUEST_FAILED",
      });
      snapshots.set(market, snapshot);
      snapshotStates.set(market, UI_STATE.API_ERROR);
      if (marketSwitch?.getActive() === market) renderActiveMarket();
      globalThis.Sentry?.captureException?.(error);
    } finally {
      if (requestControllers.get(market) === requestController) {
        requestControllers.delete(market);
      }
    }
  }

  initializeDrawers();
  marketSwitch = initializeMarketScopeSwitches({
    onChange: (market) => {
      candidatePagination.reset();
      if (snapshots.has(market)) renderActiveMarket();
      else refreshSnapshot(market);
    },
  });
  initializeResearchSettings({ onChange: () => refreshSnapshot() });
  router.start();
  applyUiState(UI_STATE.LOADING);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-stock][data-market][data-symbol]");
    if (!button) return;
    const stockKey = createStockKey({
      market: button.dataset.market,
      symbol: button.dataset.symbol,
    });
    const prediction = findStock(stockKey);
    if (!prediction) return;
    selectedStockKey = stockKey;
    renderStockDetailPage(prediction, { isWatchlisted: watchlistKeys.has(stockKey) });
    router.show("stock", { stockKey });
  });
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-toggle-watchlist][data-symbol]");
    if (!button || button.disabled) return;
    const symbol = button.dataset.symbol;
    const market = button.dataset.market;
    const selected = button.getAttribute("aria-pressed") !== "true";
    const feedback = document.querySelector("[data-watchlist-feedback]");
    button.disabled = true;
    if (feedback) feedback.textContent = selected ? "正在加入自選股…" : "正在移出自選股…";
    try {
      await setWatchlistMembership({ market, symbol, selected });
      await refreshSnapshot();
      const refreshedFeedback = document.querySelector("[data-watchlist-feedback]");
      if (refreshedFeedback) refreshedFeedback.textContent = selected ? "已加入自選股。" : "已移出自選股。";
    } catch (error) {
      if (feedback) feedback.textContent = error?.message ?? "無法更新自選股。";
      globalThis.Sentry?.captureException?.(error);
    } finally {
      button.disabled = false;
    }
  });
  globalThis.addEventListener("alpha-lens:auth-change", () => refreshSnapshot());
  refreshHomeDataStatus();
  refreshSnapshot(DEFAULT_MARKET_SCOPE);
}
