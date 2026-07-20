function selectedSegment(root, name) {
  return root.querySelector(`[data-filter="${name}"] button.is-active`)?.dataset.value ?? "";
}

function numberValue(root, name) {
  const rawValue = root.querySelector(`[name="${name}"]`)?.value ?? "";
  if (rawValue.trim() === "") return null;
  const value = Number(rawValue);
  return Number.isFinite(value) ? value : null;
}

function normalizeSearchText(value) {
  return String(value ?? "").normalize("NFKC").trim().toLocaleLowerCase("zh-Hant");
}

function currentFilters(root) {
  return Object.freeze({
    searchQuery: root.querySelector('[name="stock_search"]')?.value ?? "",
    market: selectedSegment(root, "market"),
    industry: root.querySelector('[name="industry"]')?.value ?? "",
    decision: root.querySelector('[name="decision"]')?.value ?? "",
    dataQuality: root.querySelector('[name="data_quality"]')?.value ?? "",
    liquidityBucket: root.querySelector('[name="liquidity_bucket"]')?.value ?? "",
    rankScoreMin: numberValue(root, "rank_score_min"),
    pUpMin: numberValue(root, "p_up_min"),
    costProfile: root.querySelector('[name="cost_profile"]')?.value ?? "",
  });
}

function replaceOptions(select, values, allLabel) {
  if (!select) return;
  const previous = select.value;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = allLabel;
  select.append(all);
  [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-Hant")).forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

export function filterCandidateRecords(records, filters) {
  const searchQuery = normalizeSearchText(filters.searchQuery);
  return records.filter((record) => {
    if (searchQuery) {
      const searchableText = normalizeSearchText(`${record.symbol ?? ""} ${record.name ?? ""}`);
      if (!searchableText.includes(searchQuery)) return false;
    }
    if (filters.market && record.market !== filters.market) return false;
    if (filters.industry && record.industry !== filters.industry) return false;
    if (filters.decision && record.decision !== filters.decision) return false;
    if (filters.dataQuality && record.data_quality_status !== filters.dataQuality) return false;
    if (filters.liquidityBucket && record.liquidity_bucket !== filters.liquidityBucket) return false;
    if (filters.costProfile && record.cost_profile !== filters.costProfile) return false;
    if (filters.rankScoreMin !== null && (!Number.isFinite(record.rank_score) || record.rank_score < filters.rankScoreMin)) return false;
    if (filters.pUpMin !== null && (!Number.isFinite(record.calibrated_p_up) || record.calibrated_p_up < filters.pUpMin)) return false;
    return true;
  });
}

export function initializeCandidateFilters({ onChange } = {}) {
  const root = document.querySelector("[data-candidate-filters]");
  if (!root) return Object.freeze({ getFilters: () => Object.freeze({}), setRecords: () => {} });

  const searchInput = root.querySelector('[name="stock_search"]');
  const clearSearchButton = root.querySelector("[data-clear-candidate-search]");
  const syncSearchClearButton = () => {
    if (clearSearchButton) clearSearchButton.hidden = !normalizeSearchText(searchInput?.value);
  };

  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-clear-candidate-search]")) {
      if (searchInput) searchInput.value = "";
      syncSearchClearButton();
      searchInput?.focus();
      onChange?.(currentFilters(root));
      return;
    }
    const button = event.target.closest('[data-filter="market"] button[data-value]');
    if (!button) return;
    button.closest("[data-filter]").querySelectorAll("button[data-value]").forEach((item) => {
      const active = item === button;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    onChange?.(currentFilters(root));
  });
  root.addEventListener("input", () => {
    syncSearchClearButton();
    onChange?.(currentFilters(root));
  });
  root.addEventListener("change", () => onChange?.(currentFilters(root)));
  syncSearchClearButton();

  return Object.freeze({
    getFilters: () => currentFilters(root),
    setRecords: (records) => {
      replaceOptions(root.querySelector('[name="industry"]'), records.map((record) => record.industry), "全部產業");
      replaceOptions(root.querySelector('[name="liquidity_bucket"]'), records.map((record) => record.liquidity_bucket), "全部流動性");
      replaceOptions(root.querySelector('[name="cost_profile"]'), records.map((record) => record.cost_profile), "全部成本設定");
    },
  });
}
