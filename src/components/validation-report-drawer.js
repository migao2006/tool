const REPORT_ITEMS = Object.freeze([
  ["Walk-forward 結果", "尚未執行"],
  ["Locked holdout 結果", "尚未執行"],
  ["NDCG@10／20／50", "—"],
  ["Rank IC／ICIR", "—"],
  ["機率校準", "尚未驗證"],
  ["Quantile coverage", "—"],
  ["成本敏感度", "尚未執行"],
  ["基準模型比較", "尚未執行"],
]);

export function createValidationReportDrawer() {
  const rows = REPORT_ITEMS.map(
    ([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`,
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
            <span class="system-badge">RESEARCH_ONLY</span>
            <div><strong>尚未達正式驗收</strong><p>沒有可呈現的樣本外績效或 locked holdout 結果。</p></div>
          </section>
          <dl class="report-list">${rows}</dl>
          <section class="audit-note">
            <h3>已知限制</h3>
            <p>正式 point-in-time 資料、完整成本回測及 walk-forward 報告尚未匯入。</p>
          </section>
        </div>
      </div>
    </aside>`;
}
