import { createEmptyState } from "../components/empty-state.js";
import { createCandidateCard } from "../components/candidate-card.js";
import { createExcludedSecuritiesDrawer, renderExcludedSecurities } from "../components/excluded-securities-drawer.js";
import { createStatusBanner } from "../components/status-banner.js";
import { filterCandidateRecords } from "../features/candidate-filters.js";
import { eligibleStockRecords } from "../features/prediction-selection.js";

export function createCandidatesPage({ horizon }) {
  return `
    <section class="app-page" data-page="opportunities" data-horizon="${horizon}" aria-labelledby="candidates-title" hidden>
      <div class="page-heading">
        <div><span class="eyebrow">horizon=${horizon}</span><h1 id="candidates-title">5 日候選股</h1></div>
        <span class="date-badge"><small>資料日期 · as_of_date</small><span data-candidate-date>—</span></span>
      </div>
      ${createStatusBanner({ title: "尚無正式候選", description: "只有 Rank Score 排序且通過決策門檻的股票，才會出現在正式清單。" })}

      <details class="filter-panel candidate-filters" data-candidate-filters>
        <summary><span>篩選候選股</span><small>市場、產業、風險與門檻</small></summary>
        <div class="candidate-filter-content">
          <div class="segmented three-up" data-filter="market" aria-label="市場">
            <button type="button" class="is-active" data-value="" aria-pressed="true">全部</button>
            <button type="button" data-value="TWSE" aria-pressed="false">上市</button>
            <button type="button" data-value="TPEX" aria-pressed="false">上櫃</button>
          </div>
          <div class="filter-grid wide-filter-grid">
            <label><span>產業</span><select name="industry"><option value="">全部產業</option></select></label>
            <label><span>決策</span><select name="decision"><option value="">全部</option><option>CANDIDATE</option><option>WATCH</option><option>NO_TRADE</option></select></label>
            <label><span>資料品質</span><select name="data_quality"><option value="">全部可用狀態</option><option>PASS</option><option>WARN</option></select></label>
            <label><span>流動性分組</span><select name="liquidity_bucket"><option value="">全部</option></select></label>
            <label><span>Rank Score 下限</span><input name="rank_score_min" type="number" min="0" max="100" inputmode="decimal" placeholder="不限" /></label>
            <label><span>calibrated_p_up 下限</span><input name="p_up_min" type="number" min="0" max="1" step="0.01" inputmode="decimal" placeholder="不限" /></label>
            <label><span>成本設定 <small>cost_profile</small></span><select name="cost_profile"><option value="">全部成本設定</option></select></label>
          </div>
        </div>
      </details>

      <section class="panel candidate-list-panel" aria-labelledby="candidate-list-title">
        <div class="panel-heading">
          <div><span class="eyebrow">Rank Score＝當日橫斷面排名百分位</span><h2 id="candidate-list-title">正式候選清單</h2></div>
          <button class="text-button" type="button" data-open-drawer="excluded-securities">資料排除 <small>Hard fail</small>：<span data-hard-fail-count>—</span></button>
        </div>
        <p class="quantile-note">P10／P50／P90 為條件報酬分位數，不是最低、平均、最高報酬或獲利保證。</p>
        <div data-candidate-list>${createEmptyState({ title: "正在讀取", description: "正在取得正式 5 日候選資料。" })}</div>
      </section>
      ${createExcludedSecuritiesDrawer()}
    </section>`;
}

export function renderCandidatesPage(snapshot, uiState, filters = {}) {
  const root = document.querySelector('[data-page="opportunities"]');
  if (!root || !snapshot) return;
  const date = root.querySelector("[data-candidate-date]");
  if (date) date.textContent = snapshot.asOfDate ?? "—";
  const hardFailCount = root.querySelector("[data-hard-fail-count]");
  if (hardFailCount) hardFailCount.textContent = String(snapshot.excluded?.length ?? 0);
  renderExcludedSecurities(snapshot.excluded);

  const list = root.querySelector("[data-candidate-list]");
  if (!list) return;
  const canShow = snapshot.systemStatus === "PASS" && !snapshot.stale && !snapshot.dataQualityHardFail;
  const records = canShow ? filterCandidateRecords(eligibleStockRecords(snapshot), filters) : [];
  if (records.length) {
    list.innerHTML = records.map((record) => createCandidateCard(record, { horizon: snapshot.horizon })).join("");
    return;
  }
  const reasonCode = snapshot.reasonCodes?.[0] ?? (canShow ? "NO_MATCHING_ELIGIBLE_STOCKS" : "NO_FORMAL_CANDIDATES");
  list.innerHTML = createEmptyState({
    title: canShow ? "沒有符合篩選的股票" : uiState === "no_candidates" ? "今日無正式候選" : "無正式候選股",
    description: canShow ? "請調整市場或門檻；排序仍只使用 Rank Score。" : "資料或模型尚未通過正式驗收。",
    reasonCode,
  });
}
