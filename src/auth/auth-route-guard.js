const protectedSelector = ".watch-button, [data-auth-required]";

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
