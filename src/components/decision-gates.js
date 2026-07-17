import { setText } from "../core/html.js";

const GATES = Object.freeze([
  ["data_quality", "資料品質 hard gate", "DATA_QUALITY_NOT_EVALUATED"],
  ["tradability", "可交易性 gate", "TRADABILITY_NOT_EVALUATED"],
  ["liquidity_capacity", "流動性與容量 gate", "CAPACITY_NOT_EVALUATED"],
  ["market_exposure", "市場總曝險上限", "MARKET_EXPOSURE_NOT_AVAILABLE"],
  ["direction", "校準後方向機率", "DIRECTION_MODEL_NOT_AVAILABLE"],
  ["quantile", "淨報酬分位數門檻", "QUANTILE_MODEL_NOT_AVAILABLE"],
  ["rank", "排名資格", "RANK_MODEL_NOT_AVAILABLE"],
  ["position", "部位與容量限制", "POSITION_NOT_EVALUATED"],
]);

export function createDecisionGates() {
  const rows = GATES.map(
    ([key, label, reasonCode], index) => `
      <li data-gate="${key}">
        <span class="gate-step">${index + 1}</span>
        <div class="gate-main"><strong>${label}</strong><code>${reasonCode}</code></div>
        <dl><div><dt>結果</dt><dd>未評估</dd></div><div><dt>實際值</dt><dd>—</dd></div><div><dt>門檻</dt><dd>—</dd></div></dl>
      </li>`,
  ).join("");
  return `<ol class="decision-gates">${rows}</ol>`;
}

export function renderDecisionGates(gates = []) {
  const root = document.querySelector(".decision-gates");
  if (!root) return;
  const byKey = new Map(gates.map((gate) => [gate.key, gate]));
  GATES.forEach(([key, _label, defaultReason]) => {
    const row = root.querySelector(`[data-gate="${key}"]`);
    const gate = byKey.get(key);
    row?.classList.toggle("is-pass", gate?.passed === true);
    row?.classList.toggle("is-fail", gate?.passed === false);
    setText(row, ".gate-main code", gate?.reason_code ?? defaultReason);
    setText(row, "dd:nth-of-type(1)", gate?.passed === true ? "通過" : gate?.passed === false ? "未通過" : "未評估");
    setText(row, "dl > div:nth-child(2) dd", gate?.actual);
    setText(row, "dl > div:nth-child(3) dd", gate?.threshold);
  });
}
