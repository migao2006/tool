export const HOME_DATA_STATUS_CONTRACT_VERSION = "home-data-status.v1";

const MODEL_OUTPUT_STATUSES = new Set(["PASS", "RESEARCH_ONLY", "FAIL"]);

export class HomeDataStatusContractError extends Error {
	constructor(message, code = "HOME_DATA_STATUS_CONTRACT_ERROR") {
		super(message);
		this.name = "HomeDataStatusContractError";
		this.code = code;
	}
}

function optionalDate(value, field) {
	if (value === null || value === undefined || value === "") return null;
	if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) {
		throw new HomeDataStatusContractError(`${field} 不是有效日期`);
	}
	return value;
}

function optionalTimestamp(value, field) {
	if (value === null || value === undefined || value === "") return null;
	if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) {
		throw new HomeDataStatusContractError(`${field} 不是有效時間`);
	}
	return value;
}

function nonnegativeCount(value, field) {
	const count =
		typeof value === "string" && /^\d+$/u.test(value) ? Number(value) : value;
	if (!Number.isSafeInteger(count) || count < 0) {
		throw new HomeDataStatusContractError(`${field} 不是有效的非負整數`);
	}
	return count;
}

function stringArray(value, field) {
	if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
		throw new HomeDataStatusContractError(`${field} 不是有效字串陣列`);
	}
	return Object.freeze([...value]);
}

export function normalizeHomeDataStatus(row) {
	if (!row || typeof row !== "object" || Array.isArray(row)) {
		throw new HomeDataStatusContractError("資料庫同步摘要不是物件");
	}
	if (row.status_key !== "latest") {
		throw new HomeDataStatusContractError("資料庫同步摘要不是 latest 單例");
	}
	if (row.contract_version !== HOME_DATA_STATUS_CONTRACT_VERSION) {
		throw new HomeDataStatusContractError("資料庫同步摘要契約版本不相容");
	}
	if (!MODEL_OUTPUT_STATUSES.has(row.model_output_status)) {
		throw new HomeDataStatusContractError("模型輸出狀態不在允許範圍");
	}

	return Object.freeze({
		contractVersion: row.contract_version,
		asOfDate: optionalDate(row.as_of_date, "as_of_date"),
		latestAvailableAt: optionalTimestamp(
			row.latest_available_at,
			"latest_available_at",
		),
		securitiesCount: nonnegativeCount(row.securities_count, "securities_count"),
		twseSecuritiesCount: nonnegativeCount(
			row.twse_securities_count,
			"twse_securities_count",
		),
		tpexSecuritiesCount: nonnegativeCount(
			row.tpex_securities_count,
			"tpex_securities_count",
		),
		dailyBarsLatestDate: optionalDate(
			row.daily_bars_latest_date,
			"daily_bars_latest_date",
		),
		dailyBarsLatestCount: nonnegativeCount(
			row.daily_bars_latest_count,
			"daily_bars_latest_count",
		),
		twseDailyBarsLatestCount: nonnegativeCount(
			row.twse_daily_bars_latest_count,
			"twse_daily_bars_latest_count",
		),
		tpexDailyBarsLatestCount: nonnegativeCount(
			row.tpex_daily_bars_latest_count,
			"tpex_daily_bars_latest_count",
		),
		productionReadyDailyBarsCount: nonnegativeCount(
			row.production_ready_daily_bars_count,
			"production_ready_daily_bars_count",
		),
		historicalLandingCount: nonnegativeCount(
			row.historical_landing_count,
			"historical_landing_count",
		),
		historicalParsedCount: nonnegativeCount(
			row.historical_parsed_count,
			"historical_parsed_count",
		),
		historicalQuarantinedCount: nonnegativeCount(
			row.historical_quarantined_count,
			"historical_quarantined_count",
		),
		historicalProductionEligibleCount: nonnegativeCount(
			row.historical_production_eligible_count,
			"historical_production_eligible_count",
		),
		dataSourcesCount: nonnegativeCount(
			row.data_sources_count,
			"data_sources_count",
		),
		sourceCodes: stringArray(row.source_codes, "source_codes"),
		predictionRunsCount: nonnegativeCount(
			row.prediction_runs_count,
			"prediction_runs_count",
		),
		stockPredictionsCount: nonnegativeCount(
			row.stock_predictions_count,
			"stock_predictions_count",
		),
		marketPredictionsCount: nonnegativeCount(
			row.market_predictions_count,
			"market_predictions_count",
		),
		modelOutputStatus: row.model_output_status,
		reasonCodes: stringArray(row.reason_codes, "reason_codes"),
		updatedAt: optionalTimestamp(row.updated_at, "updated_at"),
	});
}
