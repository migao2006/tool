import { normalizeHorizon } from "../core/five-day-contract.js";
import { escapeHtml } from "../core/html.js";
import { formatPercent, formatRank, formatRankScore } from "../core/formatters.js";

/** @param {import('../data/prediction-api.js').PredictionRecord} prediction */
export function createCandidateCard(prediction, { horizon, compact = false } = {}) {
  const normalizedHorizon = normalizeHorizon(horizon);
  const reasonCodes = prediction.reason_codes?.map(escapeHtml).join(" · ") || "—";
  const symbol = escapeHtml(prediction.symbol ?? "");
  const detailRows = compact ? "" : `
    <dl class="candidate-values">
      <div><dt>Rank Score（當日橫斷面排名百分位）</dt><dd>${formatRankScore(prediction.rank_score)}</dd></div>
      <div><dt>全市場／產業排名</dt><dd>${formatRank(prediction.global_rank)}／${formatRank(prediction.industry_rank)}</dd></div>
      <div><dt>校準後 UP／NEUTRAL／DOWN</dt><dd>${formatPercent(prediction.calibrated_p_up)}／${formatPercent(prediction.calibrated_p_neutral)}／${formatPercent(prediction.calibrated_p_down)}</dd></div>
      <div><dt>條件報酬分位數 P10／P50／P90</dt><dd>${formatPercent(prediction.net_q10)}／${formatPercent(prediction.net_q50)}／${formatPercent(prediction.net_q90)}</dd></div>
      <div><dt>估計來回成本</dt><dd>${formatPercent(prediction.estimated_round_trip_cost)}</dd></div>
      <div><dt>資料品質</dt><dd>${escapeHtml(prediction.data_quality_status ?? "—")}</dd></div>
    </dl>
    <p class="reason-list">${reasonCodes}</p>`;
  return `
    <article class="candidate-card${compact ? " compact" : ""}" data-symbol="${symbol}" data-horizon="${normalizedHorizon}">
      <header>
        <div><strong>${symbol}</strong><span>${escapeHtml(prediction.name ?? "—")}</span></div>
        <span class="decision-badge">${escapeHtml(prediction.decision ?? "—")}</span>
      </header>
      <p class="candidate-meta">${escapeHtml(prediction.market ?? "—")} · ${escapeHtml(prediction.industry ?? "—")}</p>
      ${compact ? `<p class="compact-rank">Rank Score <strong>${formatRankScore(prediction.rank_score)}</strong> · ${formatRank(prediction.global_rank)}</p>` : detailRows}
      <button class="card-open-button" type="button" data-open-stock data-symbol="${symbol}">查看決策詳情</button>
    </article>`;
}
