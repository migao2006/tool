import { createEmptyState } from "./empty-state.js";
import { escapeHtml } from "../core/html.js";

export function createExcludedSecuritiesDrawer() {
  return `
    <aside class="drawer" data-drawer="excluded-securities" data-drawer-backdrop role="dialog"
      aria-modal="true" aria-labelledby="excluded-securities-title" aria-hidden="true" hidden>
      <div class="drawer-sheet">
        <header class="drawer-header">
          <div><span class="eyebrow">Data quality hard fail</span><h2 id="excluded-securities-title">排除清單</h2></div>
          <button type="button" class="drawer-close" data-close-drawer aria-label="關閉排除清單">完成</button>
        </header>
        <div class="drawer-content" data-excluded-list>
          ${createEmptyState({ title: "尚無排除資料", description: "匯入 point-in-time 資料後，這裡會列出股票與 reason_codes。", reasonCode: "QUALITY_RESULTS_NOT_AVAILABLE" })}
        </div>
      </div>
    </aside>`;
}

export function renderExcludedSecurities(records) {
  const root = document.querySelector("[data-excluded-list]");
  if (!root) return;
  if (!records?.length) {
    root.innerHTML = createEmptyState({
      title: "尚無排除資料",
      description: "目前沒有 data quality hard fail 股票。",
      reasonCode: "NO_HARD_FAIL_RECORDS",
    });
    return;
  }
  root.innerHTML = records.map((record) => `
    <article class="excluded-record">
      <header><strong>${escapeHtml(record.symbol ?? "—")}</strong><span>${escapeHtml(record.name ?? "—")}</span></header>
      <p>${record.reason_codes?.map(escapeHtml).join(" · ") || "DATA_QUALITY_HARD_FAIL"}</p>
    </article>`).join("");
}
