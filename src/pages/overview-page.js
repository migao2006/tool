import { createEmptyState } from "../components/empty-state.js";
import { createResearchSettingsDrawer } from "../components/research-settings-drawer.js";
import { createStatusBanner } from "../components/status-banner.js";
import { createValidationReportDrawer } from "../components/validation-report-drawer.js";

export function createOverviewPage({ horizon }) {
  return `
    <section class="app-page is-active" data-page="home" data-horizon="${horizon}" aria-labelledby="home-title">
      <div class="page-heading action-heading">
        <div><span class="eyebrow">5 個交易日 MVP</span><h1 id="home-title">今日總覽</h1></div>
        <button class="icon-text-button" type="button" data-open-drawer="research-settings">研究設定</button>
      </div>
      ${createStatusBanner()}

      <section class="contract-meta" aria-label="預測時間契約">
        <div><span>as_of_date</span><strong>—</strong></div>
        <div><span>decision_at</span><strong>—</strong></div>
        <div><span>horizon</span><strong>${horizon} 個交易日</strong></div>
      </section>

      <section class="panel" aria-labelledby="market-heading">
        <div class="panel-heading"><div><span class="eyebrow">市場總曝險</span><h2 id="market-heading">市場判斷</h2></div><span class="data-state">尚無資料</span></div>
        <div class="market-probabilities" aria-label="市場方向機率">
          <div><span>UP</span><strong>—</strong></div><div><span>NEUTRAL</span><strong>—</strong></div><div><span>DOWN</span><strong>—</strong></div>
        </div>
        <dl class="overview-facts">
          <div><dt>market_regime</dt><dd>—</dd></div>
          <div><dt>forecast_market_volatility</dt><dd>—</dd></div>
          <div><dt>market_exposure_cap</dt><dd>—</dd></div>
        </dl>
      </section>

      <section class="decision-counts" aria-label="今日決策數量">
        <article><span>CANDIDATE</span><strong>—</strong></article>
        <article><span>WATCH</span><strong>—</strong></article>
        <article><span>NO_TRADE</span><strong>—</strong></article>
        <article><span>Hard fail</span><strong>—</strong></article>
      </section>

      <section class="panel" aria-labelledby="top-candidate-title">
        <div class="panel-heading"><div><span class="eyebrow">僅按 Rank Score 排序</span><h2 id="top-candidate-title">通過門檻的前 3～5 檔</h2></div><button class="text-button" type="button" data-route="opportunities">查看候選</button></div>
        ${createEmptyState({ title: "無正式候選股", description: "資料與模型尚未通過驗收，不會以舊資料或假資料產生排名。", reasonCode: "PREDICTION_API_NOT_CONFIGURED" })}
      </section>

      <section class="panel traceability-panel" aria-labelledby="traceability-title">
        <div class="panel-heading"><h2 id="traceability-title">模型追溯</h2><span class="system-badge" data-system-status-label>RESEARCH_ONLY</span></div>
        <dl class="overview-facts"><div><dt>model_version</dt><dd>—</dd></div><div><dt>training_end_date</dt><dd>—</dd></div><div><dt>cost_profile_version</dt><dd>—</dd></div></dl>
        <button class="secondary-button full-width" type="button" data-open-drawer="validation-report">查看模型驗證報告</button>
      </section>
      ${createValidationReportDrawer()}
      ${createResearchSettingsDrawer()}
    </section>`;
}
