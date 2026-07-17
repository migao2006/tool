import { createEmptyState } from "../components/empty-state.js";
import { createStatusBanner } from "../components/status-banner.js";
import { createWatchlistCard } from "../components/watchlist-card.js";
import { isOrdinaryStock } from "../features/prediction-selection.js";

export function createWatchlistPage({ horizon }) {
  return `
    <section class="app-page" data-page="watchlist" data-horizon="${horizon}" aria-labelledby="watchlist-title" hidden>
      <div class="page-heading">
        <div><span class="eyebrow">僅追蹤，不重新計算排名</span><h1 id="watchlist-title">自選股</h1></div>
        <span class="date-badge"><small>資料日期 · as_of_date</small><span data-watchlist-date>—</span></span>
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
          <p class="quantile-note">Rank Score 為當日橫斷面排名百分位；P10／P50／P90 為條件報酬分位數。</p>
          <div data-watchlist-results>${createEmptyState({ title: "正在讀取", description: "正在同步自選股的 5 日模型輸出。" })}</div>
        </section>
      </div>
    </section>`;
}

export function renderWatchlistPage(snapshot, decisionFilter = "") {
  const root = document.querySelector('[data-page="watchlist"]');
  if (!root || !snapshot) return;
  const date = root.querySelector("[data-watchlist-date]");
  if (date) date.textContent = snapshot.asOfDate ?? "—";
  const list = root.querySelector("[data-watchlist-results]");
  const count = root.querySelector(".count-badge");
  if (!list) return;

  const canShow = snapshot.systemStatus === "PASS" && !snapshot.stale && !snapshot.dataQualityHardFail;
  const records = canShow
    ? (snapshot.watchlist ?? []).filter(isOrdinaryStock).filter((record) => !decisionFilter || record.decision === decisionFilter)
    : [];
  if (count) count.textContent = canShow ? `${records.length} 檔` : "—";
  list.innerHTML = records.length
    ? records.map(createWatchlistCard).join("")
    : createEmptyState({
      title: canShow ? "尚未加入自選股" : "尚無可追蹤的正式輸出",
      description: canShow ? "可由正式候選股或個股詳情加入。" : "資料或模型尚未通過正式驗收。",
      reasonCode: snapshot.reasonCodes?.[0] ?? "NO_WATCHLIST_PREDICTIONS",
    });
}
