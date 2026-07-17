const STORAGE_KEY = "alpha-lens:five-day-research-settings";

function restoreForm(form) {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    saved = {};
  }
  Object.entries(saved).forEach(([name, value]) => {
    const field = form.elements.namedItem(name);
    if (field && typeof value === "string") field.value = value;
  });
}

export function initializeResearchSettings() {
  const form = document.querySelector("[data-research-settings]");
  if (!(form instanceof HTMLFormElement)) return;
  restoreForm(form);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form).entries());
    const feedback = form.querySelector("[data-settings-feedback]");
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
      if (feedback) feedback.textContent = "已儲存於此裝置；尚未送入模型或回測。";
    } catch {
      if (feedback) feedback.textContent = "無法儲存裝置偏好。";
    }
  });
}
