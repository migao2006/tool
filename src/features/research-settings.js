const STORAGE_KEY = "alpha-lens:five-day-research-settings";
const NUMERIC_RULES = Object.freeze({
  commission_discount: { minimum: Number.EPSILON, maximum: 1 },
  minimum_fee: { minimum: 0 },
  estimated_order_notional_ntd: { minimum: Number.EPSILON },
  max_adv_participation: { minimum: Number.EPSILON, maximum: 1 },
  max_single_position: { minimum: 0, maximum: 1 },
  max_industry_position: { minimum: 0, maximum: 1 },
  max_market_exposure: { minimum: 0, maximum: 1 },
});
const COST_PROFILES = new Set(["low_cost", "base_cost", "stressed_cost", "extreme_cost"]);

function loadStoredValues() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function normalizedSettings(values) {
  const settings = {};
  Object.entries(values).forEach(([name, value]) => {
    if (value === "" || value === null || value === undefined) return;
    const rule = NUMERIC_RULES[name];
    if (rule) {
      const numeric = Number(value);
      if (Number.isFinite(numeric)
        && numeric >= rule.minimum
        && (rule.maximum === undefined || numeric <= rule.maximum)) {
        settings[name] = numeric;
      }
      return;
    }
    if (name === "cost_profile" && COST_PROFILES.has(String(value))) {
      settings[name] = String(value);
    }
  });
  return Object.freeze(settings);
}

export function readResearchSettings() {
  return normalizedSettings(loadStoredValues());
}

export function initializeResearchSettings({ onChange } = {}) {
  const form = document.querySelector("[data-research-settings]");
  if (!(form instanceof HTMLFormElement)) return;
  const saved = loadStoredValues();
  Object.entries(saved).forEach(([name, value]) => {
    const field = form.elements.namedItem(name);
    if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) field.value = String(value);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const feedback = form.querySelector("[data-settings-feedback]");
    if (feedback) feedback.textContent = "";
    if (!form.reportValidity()) {
      if (feedback) feedback.textContent = "請修正超出允許範圍的設定。";
      return;
    }
    const settings = normalizedSettings(Object.fromEntries(new FormData(form).entries()));
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
      if (feedback) feedback.textContent = "已儲存裝置偏好；目前仍顯示已發布快照的成本設定。";
      onChange?.(settings);
    } catch {
      if (feedback) feedback.textContent = "無法儲存這台裝置的研究設定。";
    }
  });
}
