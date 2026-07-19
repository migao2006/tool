import { formatDateTime } from "../core/formatters.js?v=mobile-ui-1";
import { escapeHtml } from "../core/html.js";
import { HOME_DATA_STATE } from "../core/ui-state.js?v=home-data-1";

function formatCount(value) {
	return Number.isSafeInteger(value)
		? new Intl.NumberFormat("zh-TW").format(value)
		: "—";
}

function statusMessage(title, description, reasonCode = "") {
	return `
    <div class="home-data-message" role="status">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(description)}</p>
      ${reasonCode ? `<code class="reason-code">${escapeHtml(reasonCode)}</code>` : ""}
    </div>`;
}

function readyContent(status) {
	const sourceSummary = status.sourceCodes.length
		? status.sourceCodes.join("、")
		: "尚未提供來源代碼";
	const reasonCodes = status.reasonCodes.length
		? status.reasonCodes.map(escapeHtml).join("、")
		: "—";
	return `
    <div class="home-data-grid">
      <article>
        <span>行情日期</span>
        <strong>${escapeHtml(status.asOfDate ?? "—")}</strong>
        <small>資料庫最新 available_at（含研究資料）：${escapeHtml(formatDateTime(status.latestAvailableAt))}</small>
      </article>
      <article>
        <span>證券主檔</span>
        <strong>${formatCount(status.securitiesCount)} 檔</strong>
        <small>上市 ${formatCount(status.twseSecuritiesCount)}／上櫃 ${formatCount(status.tpexSecuritiesCount)} · 非候選股數</small>
      </article>
      <article>
        <span>最新日線覆蓋</span>
        <strong>${formatCount(status.dailyBarsLatestCount)} 檔</strong>
        <small>${escapeHtml(status.dailyBarsLatestDate ?? "—")} · 上市 ${formatCount(status.twseDailyBarsLatestCount)}／上櫃 ${formatCount(status.tpexDailyBarsLatestCount)}</small>
      </article>
      <article>
        <span>執行旗標完整</span>
        <strong>${formatCount(status.productionReadyDailyBarsCount)} 檔</strong>
        <small>僅通過公司行動與開收盤旗標，非正式 data quality</small>
      </article>
    </div>

    <dl class="home-data-details">
      <div>
        <dt>歷史 landing</dt>
        <dd>${formatCount(status.historicalLandingCount)}</dd>
      </div>
      <div>
        <dt>已解析 parsed</dt>
        <dd>${formatCount(status.historicalParsedCount)}</dd>
      </div>
      <div>
        <dt>隔離 quarantine</dt>
        <dd>${formatCount(status.historicalQuarantinedCount)}</dd>
      </div>
      <div>
        <dt>production eligible</dt>
        <dd>${formatCount(status.historicalProductionEligibleCount)}</dd>
      </div>
    </dl>

    <div class="home-data-summary">
      <div><span>資料來源</span><strong>${formatCount(status.dataSourcesCount)}</strong><small>${escapeHtml(sourceSummary)}</small></div>
      <div><span>5 日模型執行</span><strong>${formatCount(status.predictionRunsCount)}</strong><small>最新一輪：個股輸出 ${formatCount(status.stockPredictionsCount)}／市場輸出 ${formatCount(status.marketPredictionsCount)}</small></div>
      <div><span>模型輸出狀態</span><strong>${escapeHtml(status.modelOutputStatus)}</strong><small>${reasonCodes}</small></div>
    </div>
    <p class="home-data-updated">同步摘要更新：${escapeHtml(formatDateTime(status.updatedAt))}</p>`;
}

export function createHomeDataStatusPanel() {
	return `
    <section class="panel home-data-panel" aria-labelledby="home-data-title" data-home-data-status data-state="loading">
      <div class="panel-heading">
        <div><span class="eyebrow">Supabase 同步狀態</span><h2 id="home-data-title">資料庫同步摘要</h2></div>
        <div class="home-data-badges" aria-label="資料用途">
          <span class="data-state">RAW DATA</span>
          <span class="data-state">RESEARCH_ONLY</span>
        </div>
      </div>
      <p class="home-data-disclaimer">只顯示資料落地與覆蓋狀態，不是模型預測；不會產生市場機率或候選股。</p>
      <div data-home-data-content aria-live="polite">
        ${statusMessage("正在讀取資料庫同步狀態", "透過受 RLS 保護的唯讀摘要取得最新資訊。")}
      </div>
    </section>`;
}

export function renderHomeDataStatus(status, state, { reasonCode = "" } = {}) {
	const root = document.querySelector("[data-home-data-status]");
	const content = root?.querySelector("[data-home-data-content]");
	if (!root || !content) return;
	root.dataset.state = state;
	if (state === HOME_DATA_STATE.READY && status) {
		content.innerHTML = readyContent(status);
		return;
	}
	if (state === HOME_DATA_STATE.EMPTY) {
		content.innerHTML = statusMessage(
			"尚無同步摘要",
			"資料庫尚未建立 latest 摘要列，模型區域維持空白。",
			"HOME_DATA_STATUS_EMPTY",
		);
		return;
	}
	if (state === HOME_DATA_STATE.ERROR) {
		content.innerHTML = statusMessage(
			"無法讀取同步摘要",
			"資料庫連線或公開唯讀權限目前不可用；未以舊資料或假資料替代。",
			reasonCode || "HOME_DATA_STATUS_REQUEST_FAILED",
		);
		return;
	}
	content.innerHTML = statusMessage(
		"正在讀取資料庫同步狀態",
		"透過受 RLS 保護的唯讀摘要取得最新資訊。",
	);
}
