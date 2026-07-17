const NAVIGATION_ITEMS = Object.freeze([
  { route: "home", label: "總覽", iconClass: "tab-icon-home" },
  { route: "opportunities", label: "5 日候選", iconClass: "tab-icon-opportunities" },
  { route: "watchlist", label: "自選", iconClass: "tab-icon-watchlist" },
]);

export function createBottomNavigation() {
  const items = NAVIGATION_ITEMS.map(
    ({ route, label, iconClass }, index) => `
      <button type="button" class="${index === 0 ? "is-active" : ""}" data-route="${route}"
        ${index === 0 ? 'aria-current="page"' : ""}>
        <span class="tab-icon ${iconClass}" aria-hidden="true"></span>
        <span class="tab-label">${label}</span>
      </button>`,
  ).join("");

  return `<nav class="bottom-nav" aria-label="主要導覽">${items}</nav>`;
}
