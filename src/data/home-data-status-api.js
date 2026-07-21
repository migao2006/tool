import { publicConfig } from "../core/public-config.js?v=home-data-2";
import { normalizeHomeDataStatus } from "./home-data-status-contract.js?v=home-data-1";
import { createRequestSignal } from "./request-signal.js?v=request-signal-1";
import { createSupabaseClient } from "./supabase-client.js?v=auth-6";

const HOME_DATA_STATUS_FIELDS = Object.freeze([
	"status_key",
	"contract_version",
	"as_of_date",
	"latest_available_at",
	"securities_count",
	"twse_securities_count",
	"tpex_securities_count",
	"daily_bars_latest_date",
	"daily_bars_latest_count",
	"twse_daily_bars_latest_count",
	"tpex_daily_bars_latest_count",
	"production_ready_daily_bars_count",
	"historical_landing_count",
	"historical_parsed_count",
	"historical_quarantined_count",
	"historical_production_eligible_count",
	"data_sources_count",
	"source_codes",
	"prediction_runs_count",
	"stock_predictions_count",
	"market_predictions_count",
	"model_output_status",
	"reason_codes",
	"updated_at",
]);

export class HomeDataStatusApiError extends Error {
	constructor(message, code, options = {}) {
		super(message, options);
		this.name = "HomeDataStatusApiError";
		this.code = code;
	}
}

export async function loadHomeDataStatus({
	signal,
	config = publicConfig,
} = {}) {
	const client = await createSupabaseClient(config);
	if (!client) {
		throw new HomeDataStatusApiError(
			"Supabase 尚未完成連接",
			"HOME_DATA_STATUS_NOT_CONFIGURED",
		);
	}

	const timeoutMs = Number.isFinite(config.homeDataStatusTimeoutMs) &&
		config.homeDataStatusTimeoutMs > 0
		? config.homeDataStatusTimeoutMs
		: 12_000;
	const request = createRequestSignal(signal, timeoutMs);

	try {
		let query = client
			.from("home_data_status")
			.select(HOME_DATA_STATUS_FIELDS.join(","))
			.eq("status_key", "latest")
			.maybeSingle();
		if (typeof query.abortSignal === "function") {
			query = query.abortSignal(request.signal);
		}

		const { data, error } = await query;
		if (request.timedOut()) {
			throw new HomeDataStatusApiError(
				"資料庫同步摘要回應逾時",
				"HOME_DATA_STATUS_TIMEOUT",
				{ cause: error },
			);
		}
		if (error) {
			throw new HomeDataStatusApiError(
				"無法讀取資料庫同步摘要",
				"HOME_DATA_STATUS_REQUEST_FAILED",
				{ cause: error },
			);
		}
		if (!data) return null;

		try {
			return normalizeHomeDataStatus(data);
		} catch (error) {
			throw new HomeDataStatusApiError(
				"資料庫同步摘要格式不相容",
				error?.code ?? "HOME_DATA_STATUS_CONTRACT_ERROR",
				{ cause: error },
			);
		}
	} catch (error) {
		if (request.timedOut() && error?.code !== "HOME_DATA_STATUS_TIMEOUT") {
			throw new HomeDataStatusApiError(
				"資料庫同步摘要回應逾時",
				"HOME_DATA_STATUS_TIMEOUT",
				{ cause: error },
			);
		}
		throw error;
	} finally {
		request.cleanup();
	}
}
