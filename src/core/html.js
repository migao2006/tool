const HTML_ENTITIES = Object.freeze({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;",
});

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/gu, (character) => HTML_ENTITIES[character]);
}
