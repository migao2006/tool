import { createEmptyState } from "../components/empty-state.js";
import { createStatusBanner } from "../components/status-banner.js";

export function createWatchlistPage({ horizon }) {
  return `
    <section class="app-page" data-page="watchlist" data-horizon="${horizon}" aria-labelledby="watchlist-title" hidden>
      <div class="page-heading">
        <div><span class="eyebrow">僅追蹤，不重新計算排名</span><h1 id="watchlist-title">自選股</h1></div>
        <span class="date-badge">as_of_date：—</span>
      </div>
      <div id="auth-entry" class="auth-entry" aria-live="polite"></div>
      <div data-auth-protected>
        ${createStatusBanner({ title: "尚無可追蹤的正式輸出", description: "自選股會沿用每日推論結果，不在前端重新計算 Rank Score。" })}
        <div class="segmented four-up watch-filters" data-filter="watch-decision" aria-label="決策篩選">
          <button type="button" class="is-active" data-value="all" aria-pressed="true">全部</button>
          <button type="button" data-value="CANDIDATE" aria-pressed="false">CANDIDATE</button>
          <button type="button" data-value="WATCH" aria-pressed="false">WATCH</button>
          <button type="button" data-value="NO_TRADE" aria-pressed="false">NO_TRADE</button>
        </div>
        <section class="panel watch-panel" aria-labelledby="watch-list-heading">
          <div class="panel-heading"><div><span class="eyebrow">horizon=${horizon}</span><h2 id="watch-list-heading">追蹤清單</h2></div><span class="count-badge">—</span></div>
          <p class="quantile-note">顯示 Rank Score、global_rank、決策、校準機率、net quantiles、資料品質、原因及前一交易日變化。</p>
          ${createEmptyState({ title: "尚未加入自選股", description: "正式候選資料可用後，才能由候選股或個股詳情加入。", reasonCode: "NO_WATCHLIST_PREDICTIONS" })}
        </section>
      </div>
    </section>`;
}
