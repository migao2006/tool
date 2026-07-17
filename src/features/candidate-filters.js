export function initializeSegmentedFilters() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter] button[data-value]");
    if (!button) return;
    const group = button.closest("[data-filter]");
    group.querySelectorAll("button[data-value]").forEach((item) => {
      const isActive = item === button;
      item.classList.toggle("is-active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });
  });
}
