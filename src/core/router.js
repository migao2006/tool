import { stockKeyFromRoute, stockRoutePath } from "./market-scope.js";

const MAIN_ROUTES = new Set(["home", "opportunities", "watchlist"]);
const ROUTE_TITLES = Object.freeze({
  home: "今日總覽",
  opportunities: "5 日候選股",
  stock: "個股決策詳情",
  watchlist: "自選股",
});

function setScrollPosition(top) {
  const root = document.documentElement;
  root.classList.add("is-scroll-restoring");
  try {
    window.scrollTo({ top, left: 0, behavior: "auto" });
  } finally {
    root.classList.remove("is-scroll-restoring");
  }
}

function routeRequest(value, stockKey = null) {
  const parts = String(value ?? "").replace(/^#/u, "").split("/");
  const route = ROUTE_TITLES[parts[0]] ? parts[0] : "home";
  if (route !== "stock") return Object.freeze({ route, stockKey: null });
  try {
    const resolvedKey = stockKey ?? stockKeyFromRoute(parts[1], parts[2]);
    return Object.freeze({ route, stockKey: resolvedKey });
  } catch {
    return Object.freeze({ route: "home", stockKey: null });
  }
}

export function createRouter({ canActivate = () => true } = {}) {
  let currentRoute = "home";
  let currentStockKey = null;
  let previousMainRoute = "home";
  const scrollPositions = new Map();

  function show(route, { updateHash = true, restoreScroll = false, stockKey = null } = {}) {
    const requested = routeRequest(route, stockKey);
    const targetRoute = canActivate(requested.route, requested)
      ? requested.route
      : "home";
    const targetStockKey = targetRoute === "stock" ? requested.stockKey : null;
    const target = document.querySelector(`[data-page="${targetRoute}"]`);
    if (!target) return;

    scrollPositions.set(currentRoute, window.scrollY);
    if (MAIN_ROUTES.has(targetRoute)) previousMainRoute = targetRoute;
    currentRoute = targetRoute;
    currentStockKey = targetStockKey;

    document.querySelectorAll("[data-page]").forEach((page) => {
      const isActive = page === target;
      page.hidden = !isActive;
      page.classList.toggle("is-active", isActive);
    });

    const navigationRoute = MAIN_ROUTES.has(targetRoute) ? targetRoute : previousMainRoute;
    document.querySelectorAll(".bottom-nav [data-route]").forEach((button) => {
      const isActive = button.dataset.route === navigationRoute;
      button.classList.toggle("is-active", isActive);
      button.toggleAttribute("aria-current", isActive);
      if (isActive) button.setAttribute("aria-current", "page");
    });

    document.title = `Alpha Lens｜${ROUTE_TITLES[targetRoute]}`;
    const targetHash = targetStockKey
      ? `#${stockRoutePath(targetStockKey)}`
      : `#${targetRoute}`;
    if (updateHash && window.location.hash !== targetHash) {
      window.history.pushState({ route: targetRoute, stockKey: targetStockKey }, "", targetHash);
    } else if (!updateHash && window.location.hash && window.location.hash !== targetHash) {
      window.history.replaceState({ route: targetRoute, stockKey: targetStockKey }, "", targetHash);
    }

    const nextScroll = restoreScroll ? scrollPositions.get(targetRoute) ?? 0 : 0;
    setScrollPosition(nextScroll);
  }

  function handleClick(event) {
    const routeButton = event.target.closest("[data-route]");
    if (routeButton) {
      event.preventDefault();
      show(routeButton.dataset.route);
      return;
    }

    if (event.target.closest("[data-stock-back]")) {
      show(previousMainRoute, { restoreScroll: true });
    }
  }

  function start() {
    document.addEventListener("click", handleClick);
    window.addEventListener("popstate", () => {
      show(window.location.hash.slice(1), { updateHash: false, restoreScroll: true });
    });
    show(window.location.hash.slice(1), { updateHash: false });
  }

  return Object.freeze({
    current: () => currentRoute,
    currentStockKey: () => currentStockKey,
    show,
    start,
  });
}
