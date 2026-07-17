import { createEmptyState } from "../components/empty-state.js";
import { createExcludedSecuritiesDrawer } from "../components/excluded-securities-drawer.js";
import { createStatusBanner } from "../components/status-banner.js";

export function createCandidatesPage({ horizon }) {
  return `
    <section class="app-page" data-page="opportunities" data-horizon="${horizon}" aria-labelledby="candidates-title" hidden>
      <div class="page-heading">
        <div><span class="eyebrow">horizon=${horizon}</span><h1 id="candidates-title">5 日候選股</h1></div>
        <span class="date-badge">as_of_date：—</span>
      </div>
      ${createStatusBanner({ title: "尚無正式候選", description: "只有 Rank Score 排序且通過決策門檻的股票，才會出現在正式清單。" })}

      <section class="filter-panel candidate-filters" aria-label="候選股篩選">
        <div class="segmented two-up" data-filter="market" aria-label="市場">
          <button type="button" class="is-active" data-value="listed" aria-pressed="true">上市</button>
          <button type="button" data-value="otc" aria-pressed="false">上櫃</button>
        </div>
        <div class="filter-grid wide-filter-grid">
          <label><span>產業</span><select name="industry"><option value="">全部產業</option></select></label>
          <label><span>決策</span><select name="decision"><option value="">全部</option><option>CANDIDATE</option><option>WATCH</option><option>NO_TRADE</option></select></label>
          <label><span>資料品質</span><select name="data_quality"><option value="">全部</option><option>PASS</option><option>FAIL</option></select></label>
          <label><span>流動性分組</span><select name="liquidity_bucket"><option value="">全部</option></select></label>
          <label><span>Rank Score 下限</span><input name="rank_score_min" type="number" min="0" max="100" inputmode="decimal" placeholder="不限" /></label>
          <label><span>calibrated_p_up 下限</span><input name="p_up_min" type="number" min="0" max="1" step="0.01" inputmode="decimal" placeholder="不限" /></label>
          <label><span>Cost profile</span><select name="cost_profile"><option value="">全部</option><option>low_cost</option><option>base_cost</option><option>stressed_cost</option><option>extreme_cost</option></select></label>
        </div>
      </section>

      <section class="panel candidate-list-panel" aria-labelledby="candidate-list-title">
        <div class="panel-heading">
          <div><span class="eyebrow">Rank Score＝當日橫斷面排名百分位</span><h2 id="candidate-list-title">正式候選清單</h2></div>
          <button class="text-button" type="button" data-open-drawer="excluded-securities">Hard fail：—</button>
        </div>
        <p class="quantile-note">P10／P50／P90 為條件報酬分位數，不是最低、平均、最高報酬或獲利保證。</p>
        ${createEmptyState({ title: "無正式候選股", description: "預測 API 尚未連接；不會用 placeholder 冒充模型輸出。", reasonCode: "PREDICTION_API_NOT_CONFIGURED" })}
      </section>
      ${createExcludedSecuritiesDrawer()}
    </section>`;
}
