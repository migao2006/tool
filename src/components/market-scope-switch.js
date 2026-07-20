import {
  DEFAULT_MARKET_SCOPE,
  MARKET_SCOPES,
  normalizeMarketScope,
} from "../core/market-scope.js";

export function createMarketScopeSwitch(label) {
  return `
    <div class="market-scope-switch segmented two-up" data-market-scope-switch role="group" aria-label="${label}">
      <button type="button" class="is-active" data-market-scope="TWSE" aria-pressed="true">上市</button>
      <button type="button" data-market-scope="TPEX" aria-pressed="false">上櫃</button>
    </div>`;
}

export function initializeMarketScopeSwitches({ onChange } = {}) {
  let activeMarket = DEFAULT_MARKET_SCOPE;
  const roots = [...document.querySelectorAll("[data-market-scope-switch]")];

  function setActive(value, { notify = false } = {}) {
    const nextMarket = normalizeMarketScope(value);
    const changed = nextMarket !== activeMarket;
    activeMarket = nextMarket;
    roots.forEach((root) => {
      root.querySelectorAll("button[data-market-scope]").forEach((button) => {
        const active = button.dataset.marketScope === activeMarket;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    });
    if (notify && changed) onChange?.(activeMarket);
  }

  roots.forEach((root) => {
    root.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-market-scope]");
      if (!button || !MARKET_SCOPES.includes(button.dataset.marketScope)) return;
      setActive(button.dataset.marketScope, { notify: true });
    });
  });
  setActive(activeMarket);
  return Object.freeze({
    getActive: () => activeMarket,
    setActive,
  });
}
