const marketNames = {
  listed: "上市",
  otc: "上櫃",
  etf: "ETF",
};

const state = {
  market: "listed",
  horizon: "5",
  limit: "20",
};

function activateSegment(group, value) {
  group.querySelectorAll("button").forEach((button) => {
    const active = button.dataset.value === value;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function updateContext() {
  document.querySelector("#detail-context").textContent =
    `${marketNames[state.market]} · ${state.horizon} 個交易日預測`;
  document.querySelector("#ranking-count").textContent = `Top ${state.limit}`;
}

document.querySelectorAll("[data-control]").forEach((group) => {
  group.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;

    const key = group.dataset.control;
    state[key] = button.dataset.value;
    activateSegment(group, state[key]);
    updateContext();
  });
});

document.querySelector("#top-limit").addEventListener("change", (event) => {
  state.limit = event.target.value;
  updateContext();
});

updateContext();
