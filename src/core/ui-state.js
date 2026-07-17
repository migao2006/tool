export const UI_STATE = Object.freeze({
  LOADING: "loading",
  EMPTY: "empty",
  STALE: "stale",
  DATA_QUALITY_HARD_FAIL: "data_quality_hard_fail",
  API_ERROR: "api_error",
  RESEARCH_ONLY: "research_only",
  FAIL: "fail",
  MODEL_NOT_AVAILABLE: "model_not_available",
  NO_CANDIDATES: "no_candidates",
  READY: "ready",
});

const STATE_COPY = Object.freeze({
  [UI_STATE.LOADING]: ["RESEARCH_ONLY", "正在讀取", "正在取得 5 日模型與資料狀態。"],
  [UI_STATE.EMPTY]: ["RESEARCH_ONLY", "尚無資料", "尚未匯入可供判斷的正式資料。"],
  [UI_STATE.STALE]: ["RESEARCH_ONLY", "資料已過期", "目前資料日期已超過允許門檻，不提供正式候選。"],
  [UI_STATE.DATA_QUALITY_HARD_FAIL]: ["FAIL", "資料品質未通過", "關鍵行情、公司行動或交易狀態不完整。"],
  [UI_STATE.API_ERROR]: ["FAIL", "服務暫時無法使用", "無法取得預測資料，請稍後再試。"],
  [UI_STATE.RESEARCH_ONLY]: ["RESEARCH_ONLY", "目前僅供研究", "尚未匯入可驗證的正式資料與模型輸出，不提供候選交易。"],
  [UI_STATE.FAIL]: ["FAIL", "系統驗收未通過", "目前不允許產生正式候選交易。"],
  [UI_STATE.MODEL_NOT_AVAILABLE]: ["RESEARCH_ONLY", "模型尚未完成", "指定 horizon 尚無正式模型，不會以其他期間代替。"],
  [UI_STATE.NO_CANDIDATES]: ["PASS", "今日無正式候選", "資料與模型可用，但沒有股票通過全部決策門檻。"],
  [UI_STATE.READY]: ["PASS", "系統驗證通過", "以下結果來自目前正式的 5 日模型輸出。"],
});

export function applyUiState(state) {
  const [status, title, description] = STATE_COPY[state] ?? STATE_COPY[UI_STATE.FAIL];
  document.body.dataset.uiState = state;
  document.body.dataset.systemStatus = status;
  document.querySelectorAll("[data-system-status-label]").forEach((node) => {
    node.textContent = status;
  });
  document.querySelectorAll("[data-ui-state-title]").forEach((node) => {
    node.textContent = title;
  });
  document.querySelectorAll("[data-ui-state-description]").forEach((node) => {
    node.textContent = description;
  });
}

export function resolveSnapshotUiState(snapshot) {
  if (snapshot.reasonCodes?.includes("MODEL_NOT_RELEASED")) return UI_STATE.MODEL_NOT_AVAILABLE;
  if (snapshot.stale) return UI_STATE.STALE;
  if (snapshot.dataQualityHardFail) return UI_STATE.DATA_QUALITY_HARD_FAIL;
  if (snapshot.systemStatus === "FAIL") return UI_STATE.FAIL;
  if (snapshot.systemStatus === "RESEARCH_ONLY") return UI_STATE.RESEARCH_ONLY;
  if (!snapshot.candidates?.length) return UI_STATE.NO_CANDIDATES;
  return UI_STATE.READY;
}
