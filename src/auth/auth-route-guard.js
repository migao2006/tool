const protectedSelector = '[data-route="watchlist"], .watch-button';

function blockedReason(state) {
  if (!state.available) return "unavailable";
  if (!state.ready) return "pending";
  return "signin";
}

export function installAuthRouteGuard(getState, onBlocked) {
  document.addEventListener(
    "click",
    (event) => {
      const target = event.target.closest(protectedSelector);
      const state = getState();
      if (!target || state.user) return;

      event.preventDefault();
      event.stopImmediatePropagation();
      onBlocked(blockedReason(state));
    },
    true,
  );
}

export function guardInitialProtectedRoute(state, onBlocked) {
  if (state.user || window.location.hash !== "#watchlist") return;
  document.querySelector('.bottom-nav [data-route="home"]')?.click();
  onBlocked(blockedReason(state));
}
