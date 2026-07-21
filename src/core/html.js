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

export function setText(root, selector, value, fallback = "—") {
  const node = root?.querySelector(selector);
  if (!node) return;
  const text = value === null || value === undefined || value === "" ? fallback : String(value);
  node.textContent = text;
}

export function setAllText(selector, value, fallback = "—") {
  document.querySelectorAll(selector).forEach((node) => {
    const text = value === null || value === undefined || value === "" ? fallback : String(value);
    node.textContent = text;
  });
}
