import { escapeHtml, setText } from "../core/html.js";
import { formatPercent, formatValue } from "../core/formatters.js";

const REPORT_ITEMS = Object.freeze([
  ["walk_forward", "Walk-forward 結果"],
  ["locked_holdout", "Locked holdout 結果"],
  ["ndcg", "NDCG@10／20／50"],
  ["rank_ic", "Rank IC／ICIR"],
  ["probability_calibration", "機率校準"],
  ["quantile_coverage", "Quantile coverage"],
  ["cost_sensitivity", "成本敏感度"],
  ["baseline_comparison", "基準模型比較"],
]);

export function createValidationReportDrawer() {
  const rows = REPORT_ITEMS.map(
    ([key, label]) => `<div><dt>${label}</dt><dd data-validation-field="${key}">—</dd></div>`,
  ).join("");

  return `
    <aside class="drawer" data-drawer="validation-report" data-drawer-backdrop role="dialog"
      aria-modal="true" aria-labelledby="validation-report-title" aria-hidden="true" hidden>
      <div class="drawer-sheet">
        <header class="drawer-header">
          <div><span class="eyebrow">模型稽核</span><h2 id="validation-report-title">驗證報告</h2></div>
          <button type="button" class="drawer-close" data-close-drawer aria-label="關閉驗證報告">完成</button>
        </header>
        <div class="drawer-content">
          <section class="system-banner compact" data-system-status="RESEARCH_ONLY">
            <span class="system-badge" data-validation-status>RESEARCH_ONLY</span>
            <div><strong data-validation-title>尚未達正式驗收</strong><p data-validation-description>沒有可呈現的樣本外績效或 locked holdout 結果。</p></div>
          </section>
          <dl class="report-list">${rows}</dl>
          <section class="audit-note">
            <h3>已知限制</h3>
            <ul data-known-limitations><li>正式 point-in-time 資料、完整成本回測及 walk-forward 報告尚未匯入。</li></ul>
          </section>
        </div>
      </div>
    </aside>`;
}

function formatReportValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return formatValue(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function renderValidationReport(snapshot) {
  const validation = snapshot?.validation ?? {};
  setText(document, "[data-validation-status]", snapshot?.systemStatus);
  setText(document, "[data-validation-title]", snapshot?.systemStatus === "PASS" ? "模型驗收狀態：通過" : "尚未達正式驗收");
  setText(document, "[data-validation-description]", snapshot?.systemStatus === "PASS"
    ? "以下為目前模型版本所附的樣本外驗證摘要。"
    : "沒有足以支持正式推薦的完整樣本外驗證結果。");
  setText(document, '[data-validation-field="walk_forward"]', formatReportValue(validation.walk_forward));
  setText(document, '[data-validation-field="locked_holdout"]', formatReportValue(validation.locked_holdout));
  setText(document, '[data-validation-field="ndcg"]', [validation.ndcg_10, validation.ndcg_20, validation.ndcg_50].map(formatValue).join("／"));
  setText(document, '[data-validation-field="rank_ic"]', `${formatValue(validation.rank_ic)}／${formatValue(validation.icir)}`);
  setText(document, '[data-validation-field="probability_calibration"]', formatReportValue(validation.probability_calibration));
  setText(document, '[data-validation-field="quantile_coverage"]', formatPercent(validation.quantile_coverage));
  setText(document, '[data-validation-field="cost_sensitivity"]', formatReportValue(validation.cost_sensitivity));
  setText(document, '[data-validation-field="baseline_comparison"]', formatReportValue(validation.baseline_comparison));

  const limitations = document.querySelector("[data-known-limitations]");
  if (limitations) {
    const items = validation.known_limitations?.length
      ? validation.known_limitations
      : ["尚無可驗證的已知限制報告。"];
    limitations.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  }
}
