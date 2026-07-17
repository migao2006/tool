import { createEmptyState } from "../components/empty-state.js";
import { createCandidateCard } from "../components/candidate-card.js";
import { createResearchSettingsDrawer } from "../components/research-settings-drawer.js";
import { createStatusBanner } from "../components/status-banner.js";
import { createValidationReportDrawer, renderValidationReport } from "../components/validation-report-drawer.js";
import { formatDateTime, formatPercent } from "../core/formatters.js";
import { setText } from "../core/html.js";
import { formalCandidateRecords } from "../features/prediction-selection.js";

export function createOverviewPage({ horizon }) {
  return `
    <section class="app-page is-active" data-page="home" data-horizon="${horizon}" aria-labelledby="home-title">
      <div class="page-heading action-heading">
        <div><span class="eyebrow">5 個交易日 MVP</span><h1 id="home-title">今日總覽</h1></div>
        <button class="icon-text-button" type="button" data-open-drawer="research-settings">研究設定</button>
      </div>
      ${createStatusBanner()}

      <section class="contract-meta" aria-label="預測時間契約">
        <div><span>資料日期</span><small>as_of_date</small><strong data-overview-field="as_of_date">—</strong></div>
        <div><span>決策時間</span><small>decision_at</small><strong data-overview-field="decision_at">—</strong></div>
        <div><span>horizon</span><strong>${horizon} 個交易日</strong></div>
      </section>

      <section class="panel" aria-labelledby="market-heading">
        <div class="panel-heading"><div><span class="eyebrow">市場總曝險</span><h2 id="market-heading">市場判斷</h2></div><span class="data-state">尚無資料</span></div>
        <div class="market-probabilities" aria-label="市場方向機率">
          <div><span>上漲 UP</span><strong data-overview-field="market_p_up">—</strong></div><div><span>中性 NEUTRAL</span><strong data-overview-field="market_p_neutral">—</strong></div><div><span>下跌 DOWN</span><strong data-overview-field="market_p_down">—</strong></div>
        </div>
        <dl class="overview-facts">
          <div><dt>市場狀態 <small>market_regime</small></dt><dd data-overview-field="market_regime">—</dd></div>
          <div><dt>預測市場波動 <small>forecast_market_volatility</small></dt><dd data-overview-field="forecast_market_volatility">—</dd></div>
          <div><dt>市場曝險上限 <small>market_exposure_cap</small></dt><dd data-overview-field="market_exposure_cap">—</dd></div>
        </dl>
      </section>

      <section class="decision-counts" aria-label="今日決策數量">
        <article><span>正式候選 <small>CANDIDATE</small></span><strong data-overview-count="CANDIDATE">—</strong></article>
        <article><span>觀察 <small>WATCH</small></span><strong data-overview-count="WATCH">—</strong></article>
        <article><span>不交易 <small>NO_TRADE</small></span><strong data-overview-count="NO_TRADE">—</strong></article>
        <article><span>資料排除 <small>Hard fail</small></span><strong data-overview-count="HARD_FAIL">—</strong></article>
      </section>

      <section class="panel" aria-labelledby="top-candidate-title">
        <div class="panel-heading"><div><span class="eyebrow">僅按 Rank Score 排序</span><h2 id="top-candidate-title">通過門檻的前 3～5 檔</h2></div><button class="text-button" type="button" data-route="opportunities">查看候選</button></div>
        <div data-overview-candidates>${createEmptyState({ title: "正在讀取", description: "正在取得正式 5 日模型狀態。" })}</div>
      </section>

      <section class="panel traceability-panel" aria-labelledby="traceability-title">
        <div class="panel-heading"><h2 id="traceability-title">模型追溯</h2><span class="system-badge" data-system-status-label>RESEARCH_ONLY</span></div>
        <dl class="overview-facts"><div><dt>模型版本 <small>model_version</small></dt><dd data-overview-field="model_version">—</dd></div><div><dt>訓練資料截止日 <small>training_end_date</small></dt><dd data-overview-field="training_end_date">—</dd></div><div><dt>成本設定版本 <small>cost_profile_version</small></dt><dd data-overview-field="cost_profile_version">—</dd></div></dl>
        <button class="secondary-button full-width" type="button" data-open-drawer="validation-report">查看模型驗證報告</button>
      </section>
      ${createValidationReportDrawer()}
      ${createResearchSettingsDrawer()}
    </section>`;
}

function decisionCounts(snapshot) {
  const formal = snapshot?.systemStatus === "PASS" && !snapshot.stale && !snapshot.dataQualityHardFail;
  const records = (snapshot?.predictions ?? []).filter((record) => !record.data_quality_hard_fail);
  return Object.freeze({
    CANDIDATE: formal ? records.filter((record) => record.decision === "CANDIDATE").length : null,
    WATCH: formal ? records.filter((record) => record.decision === "WATCH").length : null,
    NO_TRADE: formal ? records.filter((record) => record.decision === "NO_TRADE").length : null,
    HARD_FAIL: snapshot?.excluded?.length ?? 0,
  });
}

export function renderOverviewPage(snapshot, uiState) {
  const root = document.querySelector('[data-page="home"]');
  if (!root || !snapshot) return;
  setText(root, '[data-overview-field="as_of_date"]', snapshot.asOfDate);
  setText(root, '[data-overview-field="decision_at"]', formatDateTime(snapshot.decisionAt));
  setText(root, '[data-overview-field="market_p_up"]', formatPercent(snapshot.market.p_up));
  setText(root, '[data-overview-field="market_p_neutral"]', formatPercent(snapshot.market.p_neutral));
  setText(root, '[data-overview-field="market_p_down"]', formatPercent(snapshot.market.p_down));
  setText(root, '[data-overview-field="market_regime"]', snapshot.market.regime);
  setText(root, '[data-overview-field="forecast_market_volatility"]', formatPercent(snapshot.market.forecast_volatility));
  setText(root, '[data-overview-field="market_exposure_cap"]', formatPercent(snapshot.market.exposure_cap));
  setText(root, '[data-overview-field="model_version"]', snapshot.modelVersion);
  setText(root, '[data-overview-field="training_end_date"]', snapshot.trainingEndDate);
  setText(root, '[data-overview-field="cost_profile_version"]', snapshot.costProfileVersion);
  const counts = decisionCounts(snapshot);
  Object.entries(counts).forEach(([key, value]) => setText(root, `[data-overview-count="${key}"]`, value));

  const list = root.querySelector("[data-overview-candidates]");
  const candidates = formalCandidateRecords(snapshot).slice(0, 5);
  if (list) {
    list.innerHTML = candidates.length
      ? candidates.map((record) => createCandidateCard(record, { horizon: snapshot.horizon, compact: true })).join("")
      : createEmptyState({
        title: uiState === "no_candidates" ? "今日無正式候選" : "無正式候選股",
        description: uiState === "no_candidates" ? "今日沒有股票通過全部決策門檻。" : "資料或模型尚未通過正式驗收。",
        reasonCode: snapshot.reasonCodes?.[0] ?? "NO_FORMAL_CANDIDATES",
      });
  }
  renderValidationReport(snapshot);
}
