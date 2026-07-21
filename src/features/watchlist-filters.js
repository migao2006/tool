export function initializeWatchlistFilters({ onChange } = {}) {
  const root = document.querySelector('[data-filter="watch-decision"]');
  if (!root) return Object.freeze({ getDecision: () => "" });
  root.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    root.querySelectorAll("button[data-value]").forEach((item) => {
      const active = item === button;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    onChange?.(button.dataset.value === "all" ? "" : button.dataset.value);
  });
  return Object.freeze({
    getDecision: () => {
      const value = root.querySelector("button.is-active")?.dataset.value ?? "all";
      return value === "all" ? "" : value;
    },
  });
}
