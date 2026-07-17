import { escapeHtml } from "../core/html.js";
import { formatPercent, formatRank, formatRankScore } from "../core/formatters.js";

function rankChange(prediction) {
  if (!Number.isFinite(prediction.previous_global_rank) || !Number.isFinite(prediction.global_rank)) return "—";
  const change = prediction.previous_global_rank - prediction.global_rank;
  if (change === 0) return "持平";
  return change > 0 ? `上升 ${change} 名` : `下降 ${Math.abs(change)} 名`;
}

export function createWatchlistCard(prediction) {
  const symbol = escapeHtml(prediction.symbol ?? "");
  const reasons = prediction.reason_codes?.map(escapeHtml).join(" · ") || "—";
  const decisionChange = prediction.previous_decision && prediction.previous_decision !== prediction.decision
    ? `${escapeHtml(prediction.previous_decision)} → ${escapeHtml(prediction.decision)}`
    : "無變化";
  return `
    <article class="watchlist-card">
      <header><div><strong>${symbol}</strong><span>${escapeHtml(prediction.name ?? "—")}</span></div><span class="decision-badge">${escapeHtml(prediction.decision)}</span></header>
      <dl class="watchlist-values">
        <div><dt>Rank Score／全市場排名</dt><dd>${formatRankScore(prediction.rank_score)}／${formatRank(prediction.global_rank)}</dd></div>
        <div><dt>排名／決策變化</dt><dd>${rankChange(prediction)}／${decisionChange}</dd></div>
        <div><dt>校準後 UP／NEUTRAL／DOWN</dt><dd>${formatPercent(prediction.calibrated_p_up)}／${formatPercent(prediction.calibrated_p_neutral)}／${formatPercent(prediction.calibrated_p_down)}</dd></div>
        <div><dt>條件報酬分位數 P10／P50／P90</dt><dd>${formatPercent(prediction.net_q10)}／${formatPercent(prediction.net_q50)}／${formatPercent(prediction.net_q90)}</dd></div>
        <div><dt>資料品質</dt><dd>${escapeHtml(prediction.data_quality_status)}</dd></div>
      </dl>
      <p class="reason-list">${reasons}</p>
      <button class="card-open-button" type="button" data-open-stock data-symbol="${symbol}">查看決策詳情</button>
    </article>`;
}
