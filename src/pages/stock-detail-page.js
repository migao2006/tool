import { createDecisionGates, renderDecisionGates } from "../components/decision-gates.js";
import { createStockAuditSection } from "../components/stock-audit-section.js";
import { formatCurrency, formatPercent, formatRank, formatRankScore } from "../core/formatters.js";
import { setText } from "../core/html.js";

export function createStockDetailPage({ horizon }) {
  return `
    <section class="app-page" data-page="stock" data-horizon="${horizon}" aria-labelledby="stock-title" hidden>
      <div class="stock-page-heading">
        <button class="back-button" type="button" data-stock-back aria-label="返回上一頁">‹</button>
        <div><span class="eyebrow">${horizon} 個交易日</span><h1 id="stock-title">尚未選擇股票</h1></div>
        <button class="watch-button" type="button" aria-label="加入自選股" disabled>☆</button>
      </div>

      <section class="decision-hero" aria-label="決策摘要">
        <div><span>決策 <small>decision</small></span><strong data-stock-field="decision">未評估</strong></div>
        <div><span>主要原因 <small>reason_codes</small></span><code data-stock-field="reason_codes">NO_STOCK_SELECTED</code></div>
        <dl><div><dt>資料日期 <small>as_of_date</small></dt><dd data-stock-field="as_of_date">—</dd></div><div><dt>決策時間 <small>decision_at</small></dt><dd data-stock-field="decision_at">—</dd></div><div><dt>期間 <small>horizon</small></dt><dd data-stock-field="horizon">${horizon}</dd></div></dl>
      </section>

      <section class="panel" aria-labelledby="gate-title">
        <div class="panel-heading"><div><span class="eyebrow">固定執行順序</span><h2 id="gate-title">決策政策</h2></div><span class="data-state">尚無資料</span></div>
        ${createDecisionGates()}
      </section>

      <div class="detail-section-grid">
        <section class="panel" aria-labelledby="ranking-title">
          <h2 id="ranking-title">排名</h2>
          <dl class="field-list"><div><dt>Rank Score <small>當日橫斷面排名百分位</small></dt><dd data-stock-field="rank_score">—</dd></div><div><dt>全市場排名 <small>global_rank</small></dt><dd data-stock-field="global_rank">—</dd></div><div><dt>全市場百分位 <small>global_rank_percentile</small></dt><dd data-stock-field="global_rank_percentile">—</dd></div><div><dt>產業排名 <small>industry_rank</small></dt><dd data-stock-field="industry_rank">—</dd></div><div><dt>產業百分位 <small>industry_rank_percentile</small></dt><dd data-stock-field="industry_rank_percentile">—</dd></div></dl>
        </section>

        <section class="panel" aria-labelledby="direction-title">
          <h2 id="direction-title">校準後方向機率</h2>
          <dl class="field-list"><div><dt>上漲 <small>calibrated_p_up</small></dt><dd data-stock-field="calibrated_p_up">—</dd></div><div><dt>中性 <small>calibrated_p_neutral</small></dt><dd data-stock-field="calibrated_p_neutral">—</dd></div><div><dt>下跌 <small>calibrated_p_down</small></dt><dd data-stock-field="calibrated_p_down">—</dd></div><div><dt>校準版本 <small>calibration_version</small></dt><dd data-stock-field="calibration_version">—</dd></div></dl>
        </section>

        <section class="panel detail-wide" aria-labelledby="quantile-title">
          <div class="panel-heading"><h2 id="quantile-title">條件報酬分位數</h2><span class="data-state">非獲利保證</span></div>
          <p class="quantile-note">P10／P50／P90 是條件報酬分位數，不是最低、平均、最高報酬或獲利保證。</p>
          <dl class="quantile-fields"><div><dt>毛報酬 P10 <small>gross_q10</small></dt><dd data-stock-field="gross_q10">—</dd></div><div><dt>毛報酬 P50 <small>gross_q50</small></dt><dd data-stock-field="gross_q50">—</dd></div><div><dt>毛報酬 P90 <small>gross_q90</small></dt><dd data-stock-field="gross_q90">—</dd></div><div><dt>淨報酬 P10 <small>net_q10</small></dt><dd data-stock-field="net_q10">—</dd></div><div><dt>淨報酬 P50 <small>net_q50</small></dt><dd data-stock-field="net_q50">—</dd></div><div><dt>淨報酬 P90 <small>net_q90</small></dt><dd data-stock-field="net_q90">—</dd></div></dl>
          <dl class="field-list inline-fields"><div><dt>區間寬度 <small>interval_width</small></dt><dd data-stock-field="interval_width">—</dd></div><div><dt>校準狀態 <small>calibration_status</small></dt><dd data-stock-field="calibration_status">—</dd></div><div><dt>估計來回成本 <small>estimated_round_trip_cost</small></dt><dd data-stock-field="estimated_round_trip_cost">—</dd></div></dl>
        </section>

        <section class="panel detail-wide" aria-labelledby="risk-title">
          <h2 id="risk-title">風險與容量</h2>
          <dl class="field-list inline-fields"><div><dt>預測波動 <small>forecast_volatility</small></dt><dd data-stock-field="forecast_volatility">—</dd></div><div><dt>下行風險 <small>downside_risk</small></dt><dd data-stock-field="downside_risk">—</dd></div><div><dt>20 日均額 <small>ADV20</small></dt><dd data-stock-field="adv20">—</dd></div><div><dt>最大可下單金額</dt><dd data-stock-field="max_order_notional_ntd">—</dd></div><div><dt>單股上限</dt><dd data-stock-field="max_single_position">—</dd></div><div><dt>單產業上限</dt><dd data-stock-field="max_industry_position">—</dd></div><div><dt>市場曝險上限 <small>market_exposure_cap</small></dt><dd data-stock-field="market_exposure_cap">—</dd></div><div><dt>成本設定 <small>cost_profile</small></dt><dd data-stock-field="cost_profile">—</dd></div></dl>
        </section>
      </div>
      ${createStockAuditSection()}
    </section>`;
}

const PERCENT_FIELDS = [
  "global_rank_percentile", "industry_rank_percentile", "calibrated_p_up", "calibrated_p_neutral",
  "calibrated_p_down", "gross_q10", "gross_q50", "gross_q90", "net_q10", "net_q50", "net_q90",
  "interval_width", "estimated_round_trip_cost", "forecast_volatility", "downside_risk",
  "max_single_position", "max_industry_position", "market_exposure_cap",
];

export function renderStockDetailPage(prediction) {
  const root = document.querySelector('[data-page="stock"]');
  if (!root || !prediction) return;
  const title = root.querySelector("#stock-title");
  if (title) title.textContent = [prediction.symbol, prediction.name].filter(Boolean).join(" ") || "尚未選擇股票";
  const directFields = ["decision", "as_of_date", "decision_at", "horizon", "calibration_version", "calibration_status", "cost_profile"];
  directFields.forEach((field) => setText(root, `[data-stock-field="${field}"]`, prediction[field]));
  setText(root, '[data-stock-field="reason_codes"]', prediction.reason_codes?.join(" · ") || "—");
  setText(root, '[data-stock-field="rank_score"]', formatRankScore(prediction.rank_score));
  setText(root, '[data-stock-field="global_rank"]', formatRank(prediction.global_rank));
  setText(root, '[data-stock-field="industry_rank"]', formatRank(prediction.industry_rank));
  PERCENT_FIELDS.forEach((field) => setText(root, `[data-stock-field="${field}"]`, formatPercent(prediction[field])));
  setText(root, '[data-stock-field="adv20"]', formatCurrency(prediction.adv20));
  setText(root, '[data-stock-field="max_order_notional_ntd"]', formatCurrency(prediction.max_order_notional_ntd));
  renderDecisionGates(prediction.gates);

  const auditValues = {
    model_version: prediction.model_version,
    feature_schema_hash: prediction.feature_schema_hash,
    cost_profile_version: prediction.cost_profile_version,
    training_end_date: prediction.training_end_date,
    source_dates: prediction.source_dates ? JSON.stringify(prediction.source_dates) : null,
    latest_available_at: prediction.latest_available_at,
    data_quality_status: prediction.data_quality_status,
    reason_codes: prediction.reason_codes?.join(" · "),
  };
  Object.entries(auditValues).forEach(([field, value]) => setText(root, `[data-audit-field="${field}"]`, value));
}
