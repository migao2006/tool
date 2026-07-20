import { normalizeHorizon } from "../core/five-day-contract.js";
import { formatPercent, formatRank, formatRankScore, formatReasonCodeSummary } from "../core/formatters.js";
import { escapeHtml } from "../core/html.js";
import { createStockKey } from "../core/market-scope.js";

/** @param {import('../data/prediction-api.js').PredictionRecord} prediction */
export function createCandidateCard(prediction, { horizon, compact = false } = {}) {
  const normalizedHorizon = normalizeHorizon(horizon);
  const reasonSummary = escapeHtml(formatReasonCodeSummary(prediction.reason_codes));
  const symbol = escapeHtml(prediction.symbol ?? "");
  const market = escapeHtml(prediction.market ?? "");
  const stockKey = escapeHtml(createStockKey(prediction));
  const industry = prediction.current_industry ?? prediction.industry;
  const industryLabel = prediction.current_industry ? "最新分類" : "產業";
  const detailRows = compact ? "" : `
    <dl class="candidate-values">
      <div><dt>Rank Score（當日橫斷面排名百分位）</dt><dd>${formatRankScore(prediction.rank_score)}</dd></div>
      <div><dt>全市場／產業排名</dt><dd>${formatRank(prediction.global_rank)}／${formatRank(prediction.industry_rank)}</dd></div>
      <div><dt>校準後 UP／NEUTRAL／DOWN</dt><dd>${formatPercent(prediction.calibrated_p_up)}／${formatPercent(prediction.calibrated_p_neutral)}／${formatPercent(prediction.calibrated_p_down)}</dd></div>
      <div><dt>條件報酬分位數 P10／P50／P90</dt><dd>${formatPercent(prediction.net_q10)}／${formatPercent(prediction.net_q50)}／${formatPercent(prediction.net_q90)}</dd></div>
      <div><dt>估計來回成本</dt><dd>${formatPercent(prediction.estimated_round_trip_cost)}</dd></div>
      <div><dt>資料品質</dt><dd>${escapeHtml(prediction.data_quality_status ?? "—")}</dd></div>
    </dl>
    <p class="reason-list" data-reason-summary>${reasonSummary}</p>`;
  return `
    <article class="candidate-card${compact ? " compact" : ""}" data-symbol="${symbol}" data-market="${market}" data-stock-key="${stockKey}" data-horizon="${normalizedHorizon}">
      <header>
        <div><strong>${symbol}</strong><span>${escapeHtml(prediction.name ?? "—")}</span></div>
        <span class="decision-badge">${escapeHtml(prediction.decision ?? "—")}</span>
      </header>
      <p class="candidate-meta">${escapeHtml(prediction.market ?? "—")} · ${industryLabel}：${escapeHtml(industry ?? "尚無分類")}</p>
      ${compact ? `<p class="compact-rank">Rank Score <strong>${formatRankScore(prediction.rank_score)}</strong> · ${formatRank(prediction.global_rank)}<br>校準後 UP <strong>${formatPercent(prediction.calibrated_p_up)}</strong> · 條件 P50 <strong>${formatPercent(prediction.net_q50)}</strong></p>` : detailRows}
      <button class="card-open-button" type="button" data-open-stock data-market="${market}" data-symbol="${symbol}">查看決策詳情</button>
    </article>`;
}
