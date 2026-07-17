export function createEmptyState({ title, description, reasonCode, action = "" }) {
  return `
    <div class="large-empty-state" role="status">
      <span class="empty-symbol" aria-hidden="true">—</span>
      <strong>${title}</strong>
      <p>${description}</p>
      ${reasonCode ? `<code class="reason-code">${reasonCode}</code>` : ""}
      ${action}
    </div>`;
}
