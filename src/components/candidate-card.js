import { normalizeHorizon } from "../core/five-day-contract.js";
import { escapeHtml } from "../core/html.js";

function formatPercent(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function formatRank(value) {
  return Number.isFinite(value) ? `#${value}` : "—";
}

/** @param {import('../data/prediction-api.js').PredictionRecord} prediction */
export function createCandidateCard(prediction, { horizon }) {
  const normalizedHorizon = normalizeHorizon(horizon);
  const reasonCodes = prediction.reason_codes?.map(escapeHtml).join(" · ") || "—";
  return `
    <article class="candidate-card" data-symbol="${escapeHtml(prediction.symbol)}" data-horizon="${normalizedHorizon}">
      <header>
        <div><strong>${escapeHtml(prediction.symbol)}</strong><span>${escapeHtml(prediction.name ?? "—")}</span></div>
        <span class="decision-badge">${escapeHtml(prediction.decision ?? "—")}</span>
      </header>
      <p class="candidate-meta">${escapeHtml(prediction.market ?? "—")} · ${escapeHtml(prediction.industry ?? "—")}</p>
      <dl class="candidate-values">
        <div><dt>Rank Score（當日橫斷面排名百分位）</dt><dd>${prediction.rank_score ?? "—"}</dd></div>
        <div><dt>全市場／產業排名</dt><dd>${formatRank(prediction.global_rank)}／${formatRank(prediction.industry_rank)}</dd></div>
        <div><dt>校準後 UP／NEUTRAL／DOWN</dt><dd>${formatPercent(prediction.calibrated_p_up)}／${formatPercent(prediction.calibrated_p_neutral)}／${formatPercent(prediction.calibrated_p_down)}</dd></div>
        <div><dt>條件報酬分位數 P10／P50／P90</dt><dd>${formatPercent(prediction.net_q10)}／${formatPercent(prediction.net_q50)}／${formatPercent(prediction.net_q90)}</dd></div>
        <div><dt>估計來回成本</dt><dd>${formatPercent(prediction.estimated_round_trip_cost)}</dd></div>
        <div><dt>資料品質</dt><dd>${escapeHtml(prediction.data_quality_status ?? "—")}</dd></div>
      </dl>
      <p class="reason-list">${reasonCodes}</p>
    </article>`;
}
