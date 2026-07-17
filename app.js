import { createBottomNavigation } from "./src/components/bottom-navigation.js";
import { initializeDrawers } from "./src/components/drawer-controller.js";
import { initializeResearchSettings } from "./src/features/research-settings.js";
import { initializeSegmentedFilters } from "./src/features/candidate-filters.js";
import { CURRENT_HORIZON } from "./src/core/five-day-contract.js";
import { createRouter } from "./src/core/router.js";
import { UI_STATE, applyUiState, resolveSnapshotUiState } from "./src/core/ui-state.js";
import { loadPredictionSnapshot } from "./src/data/prediction-api.js";
import { createCandidatesPage } from "./src/pages/candidates-page.js";
import { createOverviewPage } from "./src/pages/overview-page.js";
import { createStockDetailPage } from "./src/pages/stock-detail-page.js";
import { createWatchlistPage } from "./src/pages/watchlist-page.js";

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
  initializeDrawers();
  initializeSegmentedFilters();
  initializeResearchSettings();
  router.start();
  applyUiState(UI_STATE.LOADING);

  loadPredictionSnapshot({ horizon: CURRENT_HORIZON })
    .then((snapshot) => {
      applyUiState(resolveSnapshotUiState(snapshot));
    })
    .catch((error) => {
      applyUiState(UI_STATE.API_ERROR);
      globalThis.Sentry?.captureException?.(error);
    });
}
