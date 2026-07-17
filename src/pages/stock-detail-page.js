import { createDecisionGates } from "../components/decision-gates.js";
import { createStockAuditSection } from "../components/stock-audit-section.js";

export function createStockDetailPage({ horizon }) {
  return `
    <section class="app-page" data-page="stock" data-horizon="${horizon}" aria-labelledby="stock-title" hidden>
      <div class="stock-page-heading">
        <button class="back-button" type="button" data-stock-back aria-label="返回上一頁">‹</button>
        <div><span class="eyebrow">個股決策詳情 · ${horizon} 日</span><h1 id="stock-title">尚未選擇股票</h1></div>
        <button class="watch-button" type="button" aria-label="加入自選股" disabled>☆</button>
      </div>

      <section class="decision-hero" aria-label="決策摘要">
        <div><span>decision</span><strong>未評估</strong></div>
        <div><span>主要 reason_codes</span><code>NO_STOCK_SELECTED</code></div>
        <dl><div><dt>as_of_date</dt><dd>—</dd></div><div><dt>decision_at</dt><dd>—</dd></div><div><dt>horizon</dt><dd>${horizon}</dd></div></dl>
      </section>

      <section class="panel" aria-labelledby="gate-title">
        <div class="panel-heading"><div><span class="eyebrow">固定執行順序</span><h2 id="gate-title">決策政策</h2></div><span class="data-state">尚無資料</span></div>
        ${createDecisionGates()}
      </section>

      <div class="detail-section-grid">
        <section class="panel" aria-labelledby="ranking-title">
          <h2 id="ranking-title">排名</h2>
          <dl class="field-list"><div><dt>Rank Score（當日橫斷面排名百分位）</dt><dd>—</dd></div><div><dt>global_rank</dt><dd>—</dd></div><div><dt>global_rank_percentile</dt><dd>—</dd></div><div><dt>industry_rank</dt><dd>—</dd></div><div><dt>industry_rank_percentile</dt><dd>—</dd></div></dl>
        </section>

        <section class="panel" aria-labelledby="direction-title">
          <h2 id="direction-title">校準後方向機率</h2>
          <dl class="field-list"><div><dt>calibrated_p_up</dt><dd>—</dd></div><div><dt>calibrated_p_neutral</dt><dd>—</dd></div><div><dt>calibrated_p_down</dt><dd>—</dd></div><div><dt>calibration_version</dt><dd>—</dd></div></dl>
        </section>

        <section class="panel detail-wide" aria-labelledby="quantile-title">
          <div class="panel-heading"><h2 id="quantile-title">條件報酬分位數</h2><span class="data-state">非獲利保證</span></div>
          <dl class="quantile-fields"><div><dt>gross_q10</dt><dd>—</dd></div><div><dt>gross_q50</dt><dd>—</dd></div><div><dt>gross_q90</dt><dd>—</dd></div><div><dt>net_q10</dt><dd>—</dd></div><div><dt>net_q50</dt><dd>—</dd></div><div><dt>net_q90</dt><dd>—</dd></div></dl>
          <dl class="field-list inline-fields"><div><dt>interval_width</dt><dd>—</dd></div><div><dt>calibration_status</dt><dd>—</dd></div><div><dt>estimated_round_trip_cost</dt><dd>—</dd></div></dl>
        </section>

        <section class="panel detail-wide" aria-labelledby="risk-title">
          <h2 id="risk-title">風險與容量</h2>
          <dl class="field-list inline-fields"><div><dt>forecast_volatility</dt><dd>—</dd></div><div><dt>downside_risk</dt><dd>—</dd></div><div><dt>ADV20</dt><dd>—</dd></div><div><dt>最大可下單金額</dt><dd>—</dd></div><div><dt>單股上限</dt><dd>—</dd></div><div><dt>單產業上限</dt><dd>—</dd></div><div><dt>market_exposure_cap</dt><dd>—</dd></div><div><dt>cost_profile</dt><dd>—</dd></div></dl>
        </section>
      </div>
      ${createStockAuditSection()}
    </section>`;
}
