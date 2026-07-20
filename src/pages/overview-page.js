import { createEmptyState } from "../components/empty-state.js";
import { createCandidateCard } from "../components/candidate-card.js?v=classification-1";
import { createResearchSettingsDrawer } from "../components/research-settings-drawer.js?v=debug-1";
import { createStatusBanner } from "../components/status-banner.js";
import { createHomeDataStatusPanel } from "../components/home-data-status.js?v=mobile-ui-1";
import { createMarketScopeSwitch } from "../components/market-scope-switch.js";
import { createValidationReportDrawer, renderValidationReport } from "../components/validation-report-drawer.js";
import { formatDateTime, formatPercent } from "../core/formatters.js?v=mobile-ui-1";
import { setText } from "../core/html.js";
import { marketScopeLabel } from "../core/market-scope.js";
import {
  canDisplaySnapshotRecords,
  isHistoricalResearchSnapshot,
  overviewStockRecords,
} from "../features/prediction-selection.js";

export function createOverviewPage({ horizon }) {
  return `
    <section class="app-page is-active" data-page="home" data-horizon="${horizon}" aria-labelledby="home-title">
      <div class="page-heading action-heading">
        <div><span class="eyebrow">5 個交易日 MVP</span><h1 id="home-title">今日總覽</h1></div>
        <button class="icon-text-button" type="button" data-open-drawer="research-settings">研究設定</button>
      </div>
      ${createMarketScopeSwitch("總覽市場資料集")}
      ${createStatusBanner()}

      <section class="contract-meta" aria-label="預測時間契約">
        <div><span>資料日期</span><small>as_of_date</small><strong data-overview-field="as_of_date">—</strong></div>
        <div><span>決策時間</span><small>decision_at</small><strong data-overview-field="decision_at">—</strong></div>
        <div><span>horizon</span><strong>${horizon} 個交易日</strong></div>
      </section>

      <section class="panel" aria-labelledby="market-heading">
        <div class="panel-heading"><div><span class="eyebrow">市場總曝險</span><h2 id="market-heading">市場判斷</h2></div><span class="data-state" data-market-state>尚無資料</span></div>
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
        <div class="panel-heading"><div><span class="eyebrow">僅按 Rank Score 排序</span><h2 id="top-candidate-title" data-overview-list-title>通過門檻的前 3～5 檔</h2></div><button class="text-button" type="button" data-route="opportunities">查看候選</button></div>
        <div data-overview-candidates>${createEmptyState({ title: "正在讀取", description: "正在取得正式 5 日模型狀態。" })}</div>
      </section>

      ${createHomeDataStatusPanel()}

      <section class="panel traceability-panel" aria-labelledby="traceability-title">
        <div class="panel-heading"><h2 id="traceability-title">模型追溯</h2><span class="system-badge" data-system-status-label data-traceability-status>RESEARCH_ONLY</span></div>
        <dl class="overview-facts"><div><dt>模型版本 <small>model_version</small></dt><dd data-overview-field="model_version">—</dd></div><div><dt>訓練資料截止日 <small>training_end_date</small></dt><dd data-overview-field="training_end_date">—</dd></div><div><dt>成本設定版本 <small>cost_profile_version</small></dt><dd data-overview-field="cost_profile_version">—</dd></div></dl>
        <button class="secondary-button full-width" type="button" data-open-drawer="validation-report">查看模型驗證報告</button>
      </section>
      ${createValidationReportDrawer()}
      ${createResearchSettingsDrawer()}
    </section>`;
}

function decisionCounts(snapshot) {
  const displayable = canDisplaySnapshotRecords(snapshot);
  const records = (snapshot?.predictions ?? []).filter((record) => !record.data_quality_hard_fail);
  const hasDecisions = displayable && records.some((record) => Boolean(record.decision));
  return Object.freeze({
    CANDIDATE: hasDecisions ? records.filter((record) => record.decision === "CANDIDATE").length : null,
    WATCH: hasDecisions ? records.filter((record) => record.decision === "WATCH").length : null,
    NO_TRADE: hasDecisions ? records.filter((record) => record.decision === "NO_TRADE").length : null,
    HARD_FAIL: snapshot?.excluded?.length ?? 0,
  });
}

export function renderOverviewPage(snapshot, uiState) {
  const root = document.querySelector('[data-page="home"]');
  if (!root || !snapshot) return;
  setText(root, '[data-overview-field="as_of_date"]', snapshot.asOfDate);
  const marketLabel = marketScopeLabel(snapshot.marketScope);
  setText(root, "#market-heading", `${marketLabel}市場判斷`);
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
  const marketValues = [
    snapshot.market.p_up,
    snapshot.market.p_neutral,
    snapshot.market.p_down,
    snapshot.market.forecast_volatility,
    snapshot.market.exposure_cap,
  ];
  const hasCompleteMarketOutput = marketValues.every(Number.isFinite) && Boolean(snapshot.market.regime);
  const hasAnyMarketOutput = marketValues.some(Number.isFinite) || Boolean(snapshot.market.regime);
  setText(root, "[data-market-state]", hasCompleteMarketOutput ? "已更新" : hasAnyMarketOutput ? "部分更新" : "尚無資料");
  const counts = decisionCounts(snapshot);
  Object.entries(counts).forEach(([key, value]) => {
    setText(root, `[data-overview-count="${key}"]`, value);
  });

  const list = root.querySelector("[data-overview-candidates]");
  const researchOnly = snapshot.systemStatus === "RESEARCH_ONLY";
  const historicalResearch = isHistoricalResearchSnapshot(snapshot);
  setText(
    root,
    "[data-overview-list-title]",
    historicalResearch
      ? `${marketLabel} 5 日歷史研究排序`
      : researchOnly
      ? `${marketLabel} 5 日研究排序`
      : `${marketLabel}通過門檻的前 3～5 檔`,
  );
  const candidates = overviewStockRecords(snapshot).slice(0, 5);
  if (list) {
    list.innerHTML = candidates.length
      ? candidates.map((record) => createCandidateCard(record, { horizon: snapshot.horizon, compact: true })).join("")
      : createEmptyState({
        title: researchOnly ? `${marketLabel}尚無研究結果` : uiState === "no_candidates" ? `${marketLabel}今日無正式候選` : `${marketLabel}無正式候選股`,
        description: researchOnly ? `目前${marketLabel}快照沒有可顯示的股票資料。` : uiState === "no_candidates" ? `今日${marketLabel}沒有股票通過全部決策門檻。` : `目前${marketLabel}沒有可顯示的正式候選。`,
        reasonCode: snapshot.reasonCodes?.[0] ?? (researchOnly ? "NO_RESEARCH_RESULTS" : "NO_FORMAL_CANDIDATES"),
      });
  }
  renderValidationReport(snapshot);
}
