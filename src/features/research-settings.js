const STORAGE_KEY = "alpha-lens:five-day-research-settings";
const NUMERIC_FIELDS = new Set([
  "commission_discount",
  "minimum_fee",
  "estimated_order_notional_ntd",
  "max_adv_participation",
  "max_single_position",
  "max_industry_position",
  "max_market_exposure",
]);

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
    if (NUMERIC_FIELDS.has(name)) {
      const numeric = Number(value);
      if (Number.isFinite(numeric)) settings[name] = numeric;
      return;
    }
    settings[name] = String(value);
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
    if (!form.reportValidity()) return;
    const settings = normalizedSettings(Object.fromEntries(new FormData(form).entries()));
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
      if (feedback) feedback.textContent = "已儲存，將重新讀取符合此成本與容量設定的結果。";
      onChange?.(settings);
    } catch {
      if (feedback) feedback.textContent = "無法儲存這台裝置的研究設定。";
    }
  });
}
