import { escapeHtml } from "../core/html.js";

export function createEmptyState({ title, description, reasonCode, action = "" }) {
  return `
    <div class="large-empty-state" role="status">
      <span class="empty-symbol" aria-hidden="true">—</span>
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(description)}</p>
      ${reasonCode ? `<code class="reason-code">${escapeHtml(reasonCode)}</code>` : ""}
      ${action}
    </div>`;
}
