import { initializeChoiceSheet } from "../components/choice-sheet.js";
import { decisionCategory } from "../core/decision-policy.js";

const FILTER_VALUE_LABELS = Object.freeze({
  CANDIDATE: "正式候選",
  NO_TRADE: "政策不進場",
  MISSING_REQUIRED_DATA: "政策資料未完整",
  VALIDATION_FAILED: "政策驗證未通過",
  HARD_FAIL: "資料硬性失敗",
  PASS: "通過",
  WARN: "注意",
  WATCH: "觀察",
  base_cost: "基準成本",
  extreme_cost: "極端成本",
  high: "高流動性",
  large: "高流動性",
  low: "低流動性",
  low_cost: "低成本",
  medium: "中流動性",
  mid: "中流動性",
  small: "低流動性",
  stressed_cost: "壓力成本",
});

function recordIndustry(record) {
  return record.current_industry ?? record.industry ?? null;
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
    industry: root.querySelector('[name="industry"]')?.value ?? "",
    decision: root.querySelector('[name="decision"]')?.value ?? "",
    dataQuality: root.querySelector('[name="data_quality"]')?.value ?? "",
    liquidityBucket: root.querySelector('[name="liquidity_bucket"]')?.value ?? "",
    rankScoreMin: numberValue(root, "rank_score_min"),
    pUpMin: numberValue(root, "p_up_min"),
    costProfile: root.querySelector('[name="cost_profile"]')?.value ?? "",
  });
}

function replaceOptions(select, values, allLabel, unavailableLabel) {
  if (!select) return;
  const previous = select.value;
  const counts = new Map();
  values.filter(Boolean).forEach((value) => {
    counts.set(value, (counts.get(value) ?? 0) + 1);
  });
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = counts.size ? `${allLabel}（${values.length}）` : unavailableLabel;
  select.append(all);
  [...counts.keys()].sort((a, b) => a.localeCompare(b, "zh-Hant")).forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    const label = FILTER_VALUE_LABELS[value] ?? FILTER_VALUE_LABELS[String(value).toLocaleLowerCase()] ?? value;
    option.textContent = `${label}（${counts.get(value)}）`;
    select.append(option);
  });
  select.disabled = counts.size === 0;
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

export function filterCandidateRecords(records, filters) {
  const searchQuery = normalizeSearchText(filters.searchQuery);
  return records.filter((record) => {
    if (searchQuery) {
      const searchableText = normalizeSearchText(`${record.symbol ?? ""} ${record.name ?? ""}`);
      if (!searchableText.includes(searchQuery)) return false;
    }
    if (filters.industry && recordIndustry(record) !== filters.industry) return false;
    if (filters.decision && decisionCategory(record) !== filters.decision) return false;
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
  const choiceSheet = initializeChoiceSheet(root);
  const syncSearchClearButton = () => {
    if (clearSearchButton) clearSearchButton.hidden = !normalizeSearchText(searchInput?.value);
  };
  const syncFilterSummary = () => {
    const filters = currentFilters(root);
    const activeCount = [
      filters.industry,
      filters.decision,
      filters.dataQuality,
      filters.liquidityBucket,
      filters.rankScoreMin,
      filters.pUpMin,
      filters.costProfile,
    ].filter((value) => value !== "" && value !== null).length;
    const summary = root.querySelector("[data-candidate-filter-summary]");
    const count = root.querySelector("[data-candidate-filter-count]");
    if (summary) summary.textContent = activeCount ? `已套用 ${activeCount} 項` : "產業、風險與門檻";
    if (count) count.textContent = activeCount ? `目前套用 ${activeCount} 項篩選` : "尚未套用篩選";
  };

  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-clear-candidate-search]")) {
      if (searchInput) searchInput.value = "";
      syncSearchClearButton();
      searchInput?.focus();
      onChange?.(currentFilters(root));
      return;
    }
    if (event.target.closest("[data-reset-candidate-filters]")) {
      root.querySelectorAll('[data-choice-select], input[type="number"]').forEach((control) => {
        control.value = "";
      });
      choiceSheet.syncAll();
      syncFilterSummary();
      onChange?.(currentFilters(root));
    }
  });
  root.addEventListener("input", () => {
    syncSearchClearButton();
    syncFilterSummary();
    onChange?.(currentFilters(root));
  });
  root.addEventListener("change", () => {
    choiceSheet.syncAll();
    syncFilterSummary();
    onChange?.(currentFilters(root));
  });
  syncSearchClearButton();
  syncFilterSummary();

  return Object.freeze({
    getFilters: () => currentFilters(root),
    setRecords: (records) => {
      replaceOptions(root.querySelector('[name="industry"]'), records.map(recordIndustry), "全部最新產業", "尚無產業分類");
      replaceOptions(root.querySelector('[name="decision"]'), records.map(decisionCategory), "全部決策／政策狀態", "尚無決策或政策狀態");
      replaceOptions(root.querySelector('[name="data_quality"]'), records.map((record) => record.data_quality_status), "全部資料品質", "尚無資料品質分類");
      replaceOptions(root.querySelector('[name="liquidity_bucket"]'), records.map((record) => record.liquidity_bucket), "全部流動性", "尚無流動性分類");
      replaceOptions(root.querySelector('[name="cost_profile"]'), records.map((record) => record.cost_profile), "全部成本設定", "尚無成本設定");
      choiceSheet.syncAll();
      syncFilterSummary();
    },
  });
}
