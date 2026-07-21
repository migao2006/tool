export function createStatusBanner({
  status = "RESEARCH_ONLY",
  title = "目前僅供研究",
  description = "尚未匯入可驗證的正式資料與模型輸出，不提供候選交易。",
} = {}) {
  return `
    <section class="system-banner" data-system-status="${status}" aria-label="系統驗證狀態">
      <span class="system-badge" data-system-status-label>${status}</span>
      <div data-status-copy>
        <strong data-ui-state-title>${title}</strong>
        <p data-ui-state-description>${description}</p>
      </div>
    </section>`;
}
