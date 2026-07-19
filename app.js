import { createBottomNavigation } from "./src/components/bottom-navigation.js";
import { initializeDrawers } from "./src/components/drawer-controller.js?v=debug-1";
import { initializeResearchSettings } from "./src/features/research-settings.js?v=stored-snapshot-1";
import { initializeCandidateFilters } from "./src/features/candidate-filters.js";
import { initializeWatchlistFilters } from "./src/features/watchlist-filters.js";
import { CURRENT_HORIZON } from "./src/core/five-day-contract.js";
import { createRouter } from "./src/core/router.js?v=debug-1";
import {
  HOME_DATA_STATE,
  UI_STATE,
  applyUiState,
  resolveHomeDataState,
  resolveSnapshotUiState,
} from "./src/core/ui-state.js?v=research-ui-1";
import { renderHomeDataStatus } from "./src/components/home-data-status.js?v=home-data-1";
import { loadHomeDataStatus } from "./src/data/home-data-status-api.js?v=home-data-1";
import { loadPredictionSnapshot } from "./src/data/prediction-api.js?v=stored-snapshot-1";
import { createUnavailableSnapshot } from "./src/data/prediction-contract.js?v=research-ui-1";
import { setWatchlistMembership } from "./src/data/watchlist-api.js?v=api-5";
import { isSupabaseSdkLoadError } from "./src/data/supabase-sdk-loader.js?v=auth-1";
import { createCandidatesPage, renderCandidatesPage } from "./src/pages/candidates-page.js?v=research-ui-1";
import { createOverviewPage, renderOverviewPage } from "./src/pages/overview-page.js?v=research-ui-1";
import { createStockDetailPage, renderStockDetailPage } from "./src/pages/stock-detail-page.js?v=research-ui-2";
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

  let currentSnapshot = null;
  let selectedSymbol = null;
  let watchlistSymbols = new Set();
  let requestController = null;
  const router = createRouter({
    canActivate: (route) => route !== "stock" || Boolean(selectedSymbol),
  });
  const candidateFilters = initializeCandidateFilters({
    onChange: (filters) => {
      if (currentSnapshot) renderCandidatesPage(currentSnapshot, resolveSnapshotUiState(currentSnapshot), filters);
    },
  });
  const watchlistFilters = initializeWatchlistFilters({
    onChange: (decision) => {
      if (currentSnapshot) renderWatchlistPage(currentSnapshot, decision);
    },
  });

  function renderSnapshot(snapshot, uiState) {
    currentSnapshot = snapshot;
    watchlistSymbols = new Set((snapshot.watchlist ?? []).map((record) => record.symbol));
    candidateFilters.setRecords(snapshot.candidates ?? []);
    renderOverviewPage(snapshot, uiState);
    renderCandidatesPage(snapshot, uiState, candidateFilters.getFilters());
    renderWatchlistPage(snapshot, watchlistFilters.getDecision());
    if (selectedSymbol) {
      const selected = [...(snapshot.predictions ?? []), ...(snapshot.watchlist ?? [])]
        .find((record) => record.symbol === selectedSymbol);
      if (selected) {
        renderStockDetailPage(selected, { isWatchlisted: watchlistSymbols.has(selected.symbol) });
      } else {
        selectedSymbol = null;
        if (router.current() === "stock") router.show("opportunities");
      }
    }
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

  async function refreshSnapshot() {
    requestController?.abort();
    requestController = new AbortController();
    applyUiState(UI_STATE.LOADING);
    try {
      const snapshot = await loadPredictionSnapshot({
        horizon: CURRENT_HORIZON,
        signal: requestController.signal,
      });
      const uiState = resolveSnapshotUiState(snapshot);
      applyUiState(uiState);
      renderSnapshot(snapshot, uiState);
    } catch (error) {
      if (error?.name === "AbortError") return;
      const snapshot = createUnavailableSnapshot({
        status: "FAIL",
        reasonCode: error?.code ?? "PREDICTION_API_REQUEST_FAILED",
      });
      applyUiState(UI_STATE.API_ERROR);
      renderSnapshot(snapshot, UI_STATE.API_ERROR);
      globalThis.Sentry?.captureException?.(error);
    }
  }

  initializeDrawers();
  initializeResearchSettings({ onChange: refreshSnapshot });
  router.start();
  applyUiState(UI_STATE.LOADING);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-stock][data-symbol]");
    if (!button || !currentSnapshot) return;
    const prediction = [...(currentSnapshot.predictions ?? []), ...(currentSnapshot.watchlist ?? [])]
      .find((record) => record.symbol === button.dataset.symbol);
    if (!prediction) return;
    selectedSymbol = prediction.symbol;
    renderStockDetailPage(prediction, { isWatchlisted: watchlistSymbols.has(prediction.symbol) });
    router.show("stock");
  });
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-toggle-watchlist][data-symbol]");
    if (!button || button.disabled) return;
    const symbol = button.dataset.symbol;
    const selected = button.getAttribute("aria-pressed") !== "true";
    const feedback = document.querySelector("[data-watchlist-feedback]");
    button.disabled = true;
    if (feedback) feedback.textContent = selected ? "正在加入自選股…" : "正在移出自選股…";
    try {
      await setWatchlistMembership({ symbol, selected });
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
  refreshSnapshot();
}
