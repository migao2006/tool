import { createEmptyState } from "../components/empty-state.js";
import { createCandidateCard } from "../components/candidate-card.js?v=classification-2";
import { createExcludedSecuritiesDrawer, renderExcludedSecurities } from "../components/excluded-securities-drawer.js";
import { createStatusBanner } from "../components/status-banner.js";
import { createMarketScopeSwitch } from "../components/market-scope-switch.js";
import { createCandidateFilterDrawer } from "../components/candidate-filter-drawer.js?v=classification-2";
import { marketScopeLabel } from "../core/market-scope.js";
import { filterCandidateRecords } from "../features/candidate-filters.js?v=classification-2";
import {
  canDisplaySnapshotRecords,
  displayableStockRecords,
  isHistoricalResearchSnapshot,
} from "../features/prediction-selection.js";

const CANDIDATE_BATCH_SIZE = 25;

function visibleLimit(root) {
  const value = Number.parseInt(root.dataset.candidateVisibleLimit ?? "", 10);
  return Number.isSafeInteger(value) && value > 0 ? value : CANDIDATE_BATCH_SIZE;
}

function renderPagination(root, visibleCount, totalCount) {
  const pagination = root.querySelector("[data-candidate-pagination]");
  if (!pagination) return;
  pagination.hidden = totalCount <= CANDIDATE_BATCH_SIZE;
  const summary = pagination.querySelector("[data-candidate-pagination-summary]");
  if (summary) summary.textContent = `目前顯示 ${visibleCount}／${totalCount} 檔`;
  const button = pagination.querySelector("[data-load-more-candidates]");
  if (button) {
    const moveFocusToSummary = button === document.activeElement && visibleCount >= totalCount;
    button.hidden = visibleCount >= totalCount;
    if (moveFocusToSummary) summary?.focus({ preventScroll: true });
  }
}

export function createCandidatesPage({ horizon }) {
  return `
    <section class="app-page" data-page="opportunities" data-horizon="${horizon}" aria-labelledby="candidates-title" hidden>
      <div class="page-heading">
        <div><span class="eyebrow">horizon=${horizon}</span><h1 id="candidates-title">5 日候選股</h1></div>
        <span class="date-badge"><small>資料日期 · as_of_date</small><span data-candidate-date>—</span></span>
      </div>
      ${createMarketScopeSwitch("候選股市場資料集")}
      ${createStatusBanner({ title: "尚無正式候選", description: "只有 Rank Score 排序且通過決策門檻的股票，才會出現在正式清單。" })}

      <div class="candidate-filter-stack" data-candidate-filters>
        <div class="candidate-search" role="search" aria-label="搜尋候選股">
          <label class="candidate-search-field" for="candidate-stock-search">
            <span>搜尋股票</span>
            <input id="candidate-stock-search" name="stock_search" type="search" placeholder="代號或名稱" autocomplete="off" inputmode="search" enterkeyhint="search" aria-controls="candidate-list" />
          </label>
          <button class="text-button candidate-search-clear" type="button" data-clear-candidate-search hidden>清除</button>
        </div>
        ${createCandidateFilterDrawer()}
      </div>

      <section class="panel candidate-list-panel" aria-labelledby="candidate-list-title">
        <div class="panel-heading">
          <div><span class="eyebrow">Rank Score＝當日橫斷面排名百分位</span><h2 id="candidate-list-title" data-candidate-list-title>正式候選清單</h2></div>
          <button class="text-button" type="button" data-open-drawer="excluded-securities">資料排除 <small>Hard fail</small>：<span data-hard-fail-count>—</span></button>
        </div>
        <p class="quantile-note">P10／P50／P90 為條件報酬分位數，不是最低、平均、最高報酬或獲利保證。</p>
        <div id="candidate-list" data-candidate-list>${createEmptyState({ title: "正在讀取", description: "正在取得正式 5 日候選資料。" })}</div>
        <div class="candidate-list-pagination" data-candidate-pagination hidden>
          <p data-candidate-pagination-summary role="status" aria-live="polite" tabindex="-1">目前顯示 0／0 檔</p>
          <button class="secondary-button" type="button" data-load-more-candidates>顯示更多</button>
        </div>
      </section>
      ${createExcludedSecuritiesDrawer()}
    </section>`;
}

export function initializeCandidatePagination({ onChange } = {}) {
  const root = document.querySelector('[data-page="opportunities"]');
  if (!root) return Object.freeze({ reset: () => {} });
  root.addEventListener("click", (event) => {
    if (!event.target.closest("[data-load-more-candidates]")) return;
    root.dataset.candidateVisibleLimit = String(visibleLimit(root) + CANDIDATE_BATCH_SIZE);
    onChange?.();
  });
  return Object.freeze({
    reset: () => {
      root.dataset.candidateVisibleLimit = String(CANDIDATE_BATCH_SIZE);
    },
  });
}

export function renderCandidatesPage(snapshot, uiState, filters = {}) {
  const root = document.querySelector('[data-page="opportunities"]');
  if (!root || !snapshot) return;
  const date = root.querySelector("[data-candidate-date]");
  if (date) date.textContent = snapshot.asOfDate ?? "—";
  const marketLabel = marketScopeLabel(snapshot.marketScope);
  const hardFailCount = root.querySelector("[data-hard-fail-count]");
  if (hardFailCount) hardFailCount.textContent = String(snapshot.excluded?.length ?? 0);
  renderExcludedSecurities(snapshot.excluded);

  const list = root.querySelector("[data-candidate-list]");
  if (!list) return;
  const canShow = canDisplaySnapshotRecords(snapshot);
  const researchOnly = snapshot.systemStatus === "RESEARCH_ONLY";
  const records = canShow ? filterCandidateRecords(displayableStockRecords(snapshot), filters) : [];
  const heading = root.querySelector("[data-candidate-list-title]");
  if (heading) {
    heading.textContent = isHistoricalResearchSnapshot(snapshot)
      ? `${marketLabel} 5 日歷史研究結果`
      : researchOnly ? `${marketLabel} 5 日研究結果` : `${marketLabel}正式候選清單`;
  }
  if (records.length) {
    const visibleRecords = records.slice(0, visibleLimit(root));
    list.innerHTML = visibleRecords
      .map((record) => createCandidateCard(record, { horizon: snapshot.horizon }))
      .join("");
    renderPagination(root, visibleRecords.length, records.length);
    return;
  }
  renderPagination(root, 0, 0);
  const reasonCode = snapshot.reasonCodes?.[0] ?? (canShow ? "NO_MATCHING_ELIGIBLE_STOCKS" : "NO_DISPLAYABLE_RESULTS");
  const hasSnapshotRecords = (snapshot.predictions ?? []).length > 0;
  const emptyTitle = canShow && !hasSnapshotRecords
    ? `${marketLabel}尚無研究結果`
    : canShow
    ? `${marketLabel}沒有符合搜尋或篩選的股票`
    : uiState === "no_candidates"
    ? `${marketLabel}今日無正式候選`
    : `${marketLabel}無正式候選股`;
  const emptyDescription = canShow && !hasSnapshotRecords
    ? `目前${marketLabel}資料集尚無 5 日預測快照。`
    : canShow
    ? "請調整股票代號、名稱或進階篩選；排序仍只使用 Rank Score。"
    : `目前${marketLabel}快照沒有可顯示的股票資料。`;
  list.innerHTML = createEmptyState({
    title: emptyTitle,
    description: emptyDescription,
    reasonCode,
  });
}
