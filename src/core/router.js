const MAIN_ROUTES = new Set(["home", "opportunities", "watchlist"]);
const ROUTE_TITLES = Object.freeze({
  home: "今日總覽",
  opportunities: "5 日候選股",
  stock: "個股決策詳情",
  watchlist: "自選股",
});

export function createRouter({ canActivate = () => true } = {}) {
  let currentRoute = "home";
  let previousMainRoute = "home";
  const scrollPositions = new Map();

  function show(route, { updateHash = true, restoreScroll = false } = {}) {
    const requestedRoute = ROUTE_TITLES[route] ? route : "home";
    const targetRoute = canActivate(requestedRoute) ? requestedRoute : "home";
    const target = document.querySelector(`[data-page="${targetRoute}"]`);
    if (!target) return;

    scrollPositions.set(currentRoute, window.scrollY);
    if (MAIN_ROUTES.has(targetRoute)) previousMainRoute = targetRoute;
    currentRoute = targetRoute;

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
    if (updateHash && window.location.hash !== `#${targetRoute}`) {
      window.history.pushState({ route: targetRoute }, "", `#${targetRoute}`);
    } else if (!updateHash && window.location.hash && window.location.hash !== `#${targetRoute}`) {
      window.history.replaceState({ route: targetRoute }, "", `#${targetRoute}`);
    }

    const nextScroll = restoreScroll ? scrollPositions.get(targetRoute) ?? 0 : 0;
    window.scrollTo({ top: nextScroll, left: 0, behavior: "auto" });
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

  return Object.freeze({ current: () => currentRoute, show, start });
}
