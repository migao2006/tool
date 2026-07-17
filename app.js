const mainRoutes = new Set(["home", "opportunities", "watchlist"]);
const routeTitles = {
  home: "首頁",
  opportunities: "機會股",
  stock: "個股分析",
  watchlist: "自選股",
};
const marketNames = {
  listed: "上市",
  otc: "上櫃",
  etf: "ETF",
};

const state = {
  route: "home",
  previousMain: "home",
  opportunityHorizon: "5",
  opportunityMarket: "listed",
  stockHorizon: "5",
  watchMode: "watchlist",
  scrollPositions: new Map(),
};

function activateSegment(group, value) {
  group.querySelectorAll("button[data-value]").forEach((button) => {
    const isActive = button.dataset.value === value;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function updateOpportunityContext() {
  const context = document.querySelector("#opportunity-context");
  if (context) {
    context.textContent = `${marketNames[state.opportunityMarket]} · ${state.opportunityHorizon} 日`;
  }

  document.querySelectorAll(".horizon-summary").forEach((item) => {
    item.classList.toggle("is-selected", item.dataset.horizon === state.opportunityHorizon);
  });
}

function setBottomNavigation(route) {
  const activeRoute = mainRoutes.has(route) ? route : state.previousMain;
  document.querySelectorAll(".bottom-nav [data-route]").forEach((button) => {
    const isActive = button.dataset.route === activeRoute;
    button.classList.toggle("is-active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
}

function showPage(route, options = {}) {
  const { updateHash = true, restoreScroll = false } = options;
  const target = document.querySelector(`[data-page="${route}"]`);
  if (!target) return;

  state.scrollPositions.set(state.route, window.scrollY);
  if (mainRoutes.has(route)) state.previousMain = route;
  state.route = route;

  document.querySelectorAll("[data-page]").forEach((page) => {
    const isActive = page === target;
    page.hidden = !isActive;
    page.classList.toggle("is-active", isActive);
  });

  setBottomNavigation(route);
  document.title = `Alpha Lens｜${routeTitles[route]}`;

  if (updateHash && window.location.hash !== `#${route}`) {
    window.history.pushState({ route }, "", `#${route}`);
  }

  const nextScroll = restoreScroll ? state.scrollPositions.get(route) ?? 0 : 0;
  window.scrollTo({ top: nextScroll, left: 0, behavior: "auto" });
}

document.addEventListener("click", (event) => {
  const routeButton = event.target.closest("[data-route]");
  if (routeButton) {
    event.preventDefault();
    if (routeButton.dataset.horizon) {
      state.opportunityHorizon = routeButton.dataset.horizon;
      const horizonGroup = document.querySelector('[data-segment="opportunity-horizon"]');
      if (horizonGroup) activateSegment(horizonGroup, state.opportunityHorizon);
      updateOpportunityContext();
    }
    showPage(routeButton.dataset.route);
    return;
  }

  if (event.target.closest("[data-open-stock]")) {
    state.previousMain = mainRoutes.has(state.route) ? state.route : state.previousMain;
    showPage("stock");
    return;
  }

  if (event.target.closest("[data-stock-back]")) {
    showPage(state.previousMain, { restoreScroll: true });
    return;
  }

  const segmentButton = event.target.closest("[data-segment] button[data-value]");
  if (!segmentButton) return;

  const group = segmentButton.closest("[data-segment]");
  const value = segmentButton.dataset.value;
  activateSegment(group, value);

  switch (group.dataset.segment) {
    case "opportunity-horizon":
      state.opportunityHorizon = value;
      updateOpportunityContext();
      break;
    case "market":
      state.opportunityMarket = value;
      updateOpportunityContext();
      break;
    case "stock-horizon":
      state.stockHorizon = value;
      break;
    case "watch-mode":
      state.watchMode = value;
      document.querySelectorAll("[data-watch-view]").forEach((view) => {
        view.hidden = view.dataset.watchView !== value;
      });
      break;
    default:
      break;
  }
});

window.addEventListener("popstate", () => {
  const route = window.location.hash.slice(1);
  showPage(routeTitles[route] ? route : "home", { updateHash: false, restoreScroll: true });
});

const initialRoute = window.location.hash.slice(1);
updateOpportunityContext();
showPage(routeTitles[initialRoute] ? initialRoute : "home", { updateHash: false });
