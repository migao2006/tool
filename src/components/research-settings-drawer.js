export function createResearchSettingsDrawer() {
  return `
    <aside class="drawer" data-drawer="research-settings" data-drawer-backdrop role="dialog"
      aria-modal="true" aria-labelledby="research-settings-title" aria-hidden="true" hidden>
      <div class="drawer-sheet">
        <header class="drawer-header">
          <div><span class="eyebrow">此裝置偏好</span><h2 id="research-settings-title">研究設定</h2></div>
          <button type="button" class="drawer-close" data-close-drawer aria-label="關閉研究設定">完成</button>
        </header>
        <form class="settings-form" data-research-settings>
          <p class="form-note">只保存允許的研究偏好，不會修改模型、校準或 locked holdout。</p>
          <label><span>券商折扣 commission_discount</span><input name="commission_discount" type="number" min="0" max="1" step="0.01" inputmode="decimal" placeholder="尚未設定" /></label>
          <label><span>最低手續費 minimum_fee</span><input name="minimum_fee" type="number" min="0" step="1" inputmode="numeric" placeholder="新台幣" /></label>
          <label><span>估計下單金額 estimated_order_notional_ntd</span><input name="estimated_order_notional_ntd" type="number" min="0" step="1000" inputmode="numeric" placeholder="新台幣" /></label>
          <label><span>ADV 最大參與率 max_adv_participation</span><input name="max_adv_participation" type="number" min="0" max="1" step="0.001" inputmode="decimal" placeholder="尚未設定" /></label>
          <label><span>成本情境 cost_profile</span><select name="cost_profile"><option value="">尚未設定</option><option value="low_cost">low_cost</option><option value="base_cost">base_cost</option><option value="stressed_cost">stressed_cost</option><option value="extreme_cost">extreme_cost</option></select></label>
          <label><span>單股部位上限</span><input name="max_single_position" type="number" min="0" max="1" step="0.01" inputmode="decimal" placeholder="尚未設定" /></label>
          <label><span>單產業上限</span><input name="max_industry_position" type="number" min="0" max="1" step="0.01" inputmode="decimal" placeholder="尚未設定" /></label>
          <label><span>最大市場總曝險</span><input name="max_market_exposure" type="number" min="0" max="1" step="0.01" inputmode="decimal" placeholder="尚未設定" /></label>
          <button class="primary-button settings-save" type="submit">儲存於此裝置</button>
          <p class="settings-feedback" data-settings-feedback aria-live="polite"></p>
        </form>
      </div>
    </aside>`;
}
