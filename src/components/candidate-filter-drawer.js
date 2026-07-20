import { createChoiceSheet } from "./choice-sheet.js";

function choiceField({ id, label, name, options }) {
	return `
    <div class="candidate-filter-field" data-choice-field>
      <span id="${id}-label">${label}</span>
      <select name="${name}" data-choice-select hidden tabindex="-1" aria-hidden="true">${options}</select>
      <button class="candidate-choice-trigger" type="button" data-choice-trigger data-choice-for="${name}" data-choice-label="${label}" aria-haspopup="dialog" aria-expanded="false" aria-labelledby="${id}-label ${id}-value">
        <span id="${id}-value" data-choice-value>—</span>
      </button>
    </div>`;
}

export function createCandidateFilterDrawer() {
	return `
    <button class="candidate-filter-launch" type="button" data-open-drawer="candidate-filters" aria-haspopup="dialog">
      <span><strong>篩選候選股</strong><small data-candidate-filter-summary>產業、風險與門檻</small></span>
      <span class="candidate-filter-launch-icon" aria-hidden="true">＋</span>
    </button>
    <div class="drawer" data-drawer="candidate-filters" data-drawer-backdrop role="dialog" aria-modal="true" aria-labelledby="candidate-filter-title" aria-hidden="true" hidden>
      <section class="drawer-sheet candidate-filter-sheet">
        <header class="drawer-header">
          <div><span class="eyebrow">5 日候選</span><h2 id="candidate-filter-title">篩選候選股</h2></div>
          <button class="drawer-close" type="button" data-close-drawer>關閉</button>
        </header>
        <div class="drawer-content candidate-filter-drawer-content">
          <div class="candidate-filter-toolbar">
            <p data-candidate-filter-count>尚未套用篩選</p>
            <button class="text-button" type="button" data-reset-candidate-filters>清除全部</button>
          </div>
          <div class="candidate-filter-grid">
            ${choiceField({ id: "candidate-industry", label: "產業", name: "industry", options: '<option value="">全部產業</option>' })}
            ${choiceField({ id: "candidate-decision", label: "決策", name: "decision", options: '<option value="">全部</option><option value="CANDIDATE">正式候選</option><option value="WATCH">觀察</option><option value="NO_TRADE">不交易</option>' })}
            ${choiceField({ id: "candidate-data-quality", label: "資料品質", name: "data_quality", options: '<option value="">全部可用狀態</option><option value="PASS">通過</option><option value="WARN">注意</option>' })}
            ${choiceField({ id: "candidate-liquidity", label: "流動性分組", name: "liquidity_bucket", options: '<option value="">全部流動性</option>' })}
            <label class="candidate-filter-field"><span>Rank Score 下限</span><input name="rank_score_min" type="number" min="0" max="100" inputmode="decimal" placeholder="不限" /></label>
            <label class="candidate-filter-field"><span>校準後上漲機率下限</span><input name="p_up_min" type="number" min="0" max="1" step="0.01" inputmode="decimal" placeholder="不限" /></label>
            ${choiceField({ id: "candidate-cost-profile", label: "成本設定", name: "cost_profile", options: '<option value="">全部成本設定</option>' })}
          </div>
        </div>
        <footer class="candidate-filter-footer">
          <button class="primary-button" type="button" data-close-drawer>完成</button>
        </footer>
      </section>
    </div>
    ${createChoiceSheet()}`;
}
