import { createBottomNavigation } from "./src/components/bottom-navigation.js";
import { initializeDrawers } from "./src/components/drawer-controller.js";
import { initializeResearchSettings, readResearchSettings } from "./src/features/research-settings.js";
import { initializeCandidateFilters } from "./src/features/candidate-filters.js";
import { initializeWatchlistFilters } from "./src/features/watchlist-filters.js";
import { CURRENT_HORIZON } from "./src/core/five-day-contract.js";
import { createRouter } from "./src/core/router.js";
import { UI_STATE, applyUiState, resolveSnapshotUiState } from "./src/core/ui-state.js";
import { loadPredictionSnapshot } from "./src/data/prediction-api.js";
import { createUnavailableSnapshot } from "./src/data/prediction-contract.js";
import { createCandidatesPage, renderCandidatesPage } from "./src/pages/candidates-page.js";
import { createOverviewPage, renderOverviewPage } from "./src/pages/overview-page.js";
import { createStockDetailPage, renderStockDetailPage } from "./src/pages/stock-detail-page.js";
import { createWatchlistPage, renderWatchlistPage } from "./src/pages/watchlist-page.js";

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

  const router = createRouter();
  let currentSnapshot = null;
  let selectedSymbol = null;
  let requestController = null;
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
    candidateFilters.setRecords(snapshot.candidates ?? []);
    renderOverviewPage(snapshot, uiState);
    renderCandidatesPage(snapshot, uiState, candidateFilters.getFilters());
    renderWatchlistPage(snapshot, watchlistFilters.getDecision());
    if (selectedSymbol) {
      const selected = [...(snapshot.predictions ?? []), ...(snapshot.watchlist ?? [])]
        .find((record) => record.symbol === selectedSymbol);
      if (selected) renderStockDetailPage(selected);
    }
  }

  async function refreshSnapshot(settings = readResearchSettings()) {
    requestController?.abort();
    requestController = new AbortController();
    applyUiState(UI_STATE.LOADING);
    try {
      const snapshot = await loadPredictionSnapshot({
        horizon: CURRENT_HORIZON,
        settings,
        signal: requestController.signal,
      });
      const uiState = resolveSnapshotUiState(snapshot);
      applyUiState(uiState);
      renderSnapshot(snapshot, uiState);
    } catch (error) {
      if (error?.name === "AbortError") return;
      const snapshot = createUnavailableSnapshot({ status: "FAIL", reasonCode: "PREDICTION_API_REQUEST_FAILED" });
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
    renderStockDetailPage(prediction);
    router.show("stock");
  });
  refreshSnapshot();
}
