import { ApiError } from "./errors.ts";
import { normalizeTimeoutMs } from "./request-deadline.ts";
import { createTimedAbortSignal } from "./timed-abort.ts";
import type {
  BacktestRunRow,
  DataQualityAuditRow,
  DecisionGateRow,
  JsonRecord,
  MarketPredictionRow,
  MarketScope,
  PredictionRunRow,
  SecurityHistoryRow,
  SecurityRow,
  SnapshotRepositoryContract,
  SnapshotRows,
  StockPredictionRow,
  TradingCalendarObservationRow,
  ValidationMetricRow,
  ValidationRunRow,
} from "./types.ts";

const PAGE_SIZE = 1_000;
const SELECT_LIMIT = 5_000;
const DEFAULT_QUERY_TIMEOUT_MS = 4_000;
const SNAPSHOT_RPC_NAME = "get_prediction_snapshot_rows_v2";

export type RepositoryReadMode = "rpc" | "legacy";
type FetchLike = typeof fetch;

export interface RepositoryConfig {
  supabaseUrl: string;
  serviceRoleKey: string;
  queryTimeoutMs?: number;
  readMode?: RepositoryReadMode | string;
}

function normalizeReadMode(
  value: RepositoryConfig["readMode"],
): RepositoryReadMode {
  const mode = value?.trim().toLowerCase() || "rpc";
  if (mode === "rpc" || mode === "legacy") return mode;
  throw new ApiError(
    500,
    "PREDICTION_API_NOT_CONFIGURED",
    "Prediction snapshot read mode is invalid",
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function unwrapRpcPayload(payload: unknown): unknown {
  if (payload === null) return null;
  if (Array.isArray(payload) && payload.length === 1) {
    return unwrapRpcPayload(payload[0]);
  }
  if (isRecord(payload) && SNAPSHOT_RPC_NAME in payload) {
    return payload[SNAPSHOT_RPC_NAME];
  }
  return payload;
}

function isSnapshotRows(value: unknown): value is SnapshotRows {
  if (!isRecord(value) || !isRecord(value.run)) return false;
  const arrayFields = [
    "predictions",
    "securities",
    "currentSecurityHistory",
    "audits",
    "gates",
    "markets",
    "validationMetrics",
    "backtests",
    "calendarObservations",
  ];
  if (!arrayFields.every((field) => Array.isArray(value[field]))) return false;
  if (value.validationRun !== null && !isRecord(value.validationRun)) {
    return false;
  }
  return value.validationLinkStatus === "LINKED" ||
    value.validationLinkStatus === "MISSING" ||
    value.validationLinkStatus === "AMBIGUOUS";
}

function rpcUnavailable(status: number, payload: unknown): boolean {
  if (!isRecord(payload)) return false;
  const code = typeof payload.code === "string" ? payload.code : "";
  const message = typeof payload.message === "string" ? payload.message : "";
  return code === "PGRST202" ||
    (status === 404 && message.includes(SNAPSHOT_RPC_NAME));
}

function taipeiDate(observedAt: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(observedAt);
}

export class SnapshotRepository implements SnapshotRepositoryContract {
  readonly #restUrl: string;
  readonly #rpcUrl: string;
  readonly #queryTimeoutMs: number;
  readonly #readMode: RepositoryReadMode;

  constructor(
    readonly config: RepositoryConfig,
    readonly fetchImpl: FetchLike = fetch,
  ) {
    if (!config.supabaseUrl || !config.serviceRoleKey) {
      throw new ApiError(
        500,
        "PREDICTION_API_NOT_CONFIGURED",
        "Server configuration is missing",
      );
    }
    this.#restUrl = `${config.supabaseUrl.replace(/\/$/u, "")}/rest/v1`;
    this.#rpcUrl = `${this.#restUrl}/rpc/${SNAPSHOT_RPC_NAME}`;
    this.#queryTimeoutMs = normalizeTimeoutMs(
      config.queryTimeoutMs ?? DEFAULT_QUERY_TIMEOUT_MS,
      DEFAULT_QUERY_TIMEOUT_MS,
    );
    this.#readMode = normalizeReadMode(config.readMode);
  }

  async loadLatest(
    horizon: number,
    marketScope: MarketScope,
    parentSignal?: AbortSignal,
    observedAt: Date = new Date(),
  ): Promise<SnapshotRows | null> {
    if (!Number.isFinite(observedAt.getTime())) {
      throw new ApiError(
        500,
        "PREDICTION_API_NOT_CONFIGURED",
        "Prediction snapshot observation time is invalid",
      );
    }
    if (this.#readMode === "legacy") {
      return await this.#loadLegacy(
        horizon,
        marketScope,
        parentSignal,
        observedAt,
      );
    }
    return await this.#loadViaRpc(
      horizon,
      marketScope,
      observedAt,
      parentSignal,
    );
  }

  async #loadViaRpc(
    horizon: number,
    marketScope: MarketScope,
    observedAt: Date,
    parentSignal?: AbortSignal,
  ): Promise<SnapshotRows | null> {
    const fetchSignal = createTimedAbortSignal(
      parentSignal,
      this.#queryTimeoutMs,
    );
    try {
      const response = await this.fetchImpl(this.#rpcUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Accept-Profile": "market_data",
          "Content-Profile": "market_data",
          apikey: this.config.serviceRoleKey,
          Authorization: `Bearer ${this.config.serviceRoleKey}`,
        },
        body: JSON.stringify({
          p_horizon: horizon,
          p_market_scope: marketScope,
          p_observed_at: observedAt.toISOString(),
        }),
        cache: "no-store",
        signal: fetchSignal.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        if (rpcUnavailable(response.status, payload)) {
          throw new ApiError(
            503,
            "PREDICTION_SNAPSHOT_RPC_NOT_DEPLOYED",
            "Prediction snapshot RPC is not available",
          );
        }
        throw new ApiError(
          502,
          "PREDICTION_DATABASE_READ_FAILED",
          "Prediction snapshot RPC failed",
        );
      }
      const unwrapped = unwrapRpcPayload(payload);
      if (unwrapped === null) return null;
      if (!isSnapshotRows(unwrapped)) {
        throw new ApiError(
          502,
          "PREDICTION_DATABASE_RESPONSE_INVALID",
          "Prediction snapshot RPC response is invalid",
        );
      }
      return unwrapped;
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      if (parentSignal?.aborted) {
        throw parentSignal.reason instanceof ApiError
          ? parentSignal.reason
          : new ApiError(
            504,
            "PREDICTION_REQUEST_TIMEOUT",
            "Prediction snapshot request exceeded its deadline",
          );
      }
      if (fetchSignal.timedOut()) {
        throw new ApiError(
          504,
          "PREDICTION_DATABASE_TIMEOUT",
          "Prediction snapshot RPC timed out",
        );
      }
      throw new ApiError(
        502,
        "PREDICTION_DATABASE_READ_FAILED",
        "Prediction snapshot RPC failed",
      );
    } finally {
      fetchSignal.cleanup();
    }
  }

  async #loadLegacy(
    horizon: number,
    marketScope: MarketScope,
    signal?: AbortSignal,
    observedAt: Date = new Date(),
  ): Promise<SnapshotRows | null> {
    const runs = await this.#select<PredictionRunRow>("prediction_runs", {
      select:
        "prediction_run_id,as_of_date,decision_at,horizon,market_scope,model_bundle_version,feature_schema_hash,cost_profile_version,training_end_date,system_validation_status,source_dates,latest_available_at,candidate_count,watch_count,no_trade_count,policy_input_missing_count,policy_validation_failed_count,policy_hard_fail_count,hard_fail_count,created_at",
      horizon: `eq.${horizon}`,
      market_scope: `eq.${marketScope}`,
      decision_at: `lte.${observedAt.toISOString()}`,
      latest_available_at: `lte.${observedAt.toISOString()}`,
      created_at: `lte.${observedAt.toISOString()}`,
      order: "decision_at.desc,prediction_run_id.desc",
      limit: "1",
    }, signal);
    const run = runs[0];
    if (!run) return null;

    const runId = Number(run.prediction_run_id);
    const [predictions, audits, markets, validationRuns] = await Promise.all([
      this.#all<StockPredictionRow>("stock_predictions", {
        select:
          "stock_prediction_id,prediction_run_id,security_id,market,industry,rank_score,global_rank,global_rank_percentile,industry_rank,industry_rank_percentile,calibrated_p_up,calibrated_p_neutral,calibrated_p_down,calibration_version,gross_q10,gross_q50,gross_q90,net_q10,net_q50,net_q90,interval_width,calibration_status,forecast_volatility,downside_risk,adv20_ntd,maximum_order_notional_ntd,market_regime,market_exposure_cap,estimated_round_trip_cost,data_quality_status,decision,decision_policy_status,reason_codes",
        prediction_run_id: `eq.${runId}`,
        order: "global_rank.asc",
      }, signal),
      this.#all<DataQualityAuditRow>("data_quality_audits", {
        select:
          "security_id,quality_status,hard_fail,reason_codes,source_dates,latest_available_at",
        prediction_run_id: `eq.${runId}`,
        order: "security_id.asc",
      }, signal),
      this.#select<MarketPredictionRow>("market_predictions", {
        select:
          "market,calibrated_p_up,calibrated_p_neutral,calibrated_p_down,market_regime,forecast_market_volatility,market_exposure_cap,model_version,training_end_date",
        prediction_run_id: `eq.${runId}`,
        order: "market.asc",
      }, signal),
      this.#select<ValidationRunRow>("validation_runs", {
        select:
          "validation_run_id,validation_status,locked_holdout,frozen_config_hash,started_at,completed_at,limitations",
        model_bundle_version: `eq.${run.model_bundle_version}`,
        horizon: `eq.${horizon}`,
        completed_at: `lte.${run.created_at}`,
        order: "completed_at.desc.nullslast,validation_run_id.desc",
        limit: "2",
      }, signal),
    ]);

    const securityIds = [
      ...new Set([
        ...predictions.map((row) => row.security_id),
        ...audits.map((row) => row.security_id),
      ]),
    ];
    const predictionIds = predictions.map((row) => row.stock_prediction_id);
    const validationLinkStatus = validationRuns.length === 1
      ? "LINKED"
      : validationRuns.length > 1
      ? "AMBIGUOUS"
      : "MISSING";
    const validationRun = validationLinkStatus === "LINKED"
      ? validationRuns[0]
      : null;
    const observedDate = taipeiDate(observedAt);
    const [
      securities,
      currentSecurityHistory,
      gates,
      validationMetrics,
      backtests,
    ] = await Promise.all([
      this.#selectIn<SecurityRow>(
        "securities",
        "security_id",
        securityIds,
        "security_id,symbol,display_name,market,asset_type",
        undefined,
        {},
        signal,
      ),
      this.#selectIn<SecurityHistoryRow>(
        "security_history",
        "security_id",
        securityIds,
        "security_id,effective_from,effective_to,industry_code,industry_name,source_version,available_at",
        "security_id.asc,effective_from.desc,available_at.desc",
        {
          effective_from: `lte.${observedDate}`,
          available_at: `lte.${observedAt.toISOString()}`,
          or: `(effective_to.is.null,effective_to.gt.${observedDate})`,
        },
        signal,
      ),
      this.#selectIn<DecisionGateRow>(
        "decision_gate_results",
        "stock_prediction_id",
        predictionIds,
        "stock_prediction_id,gate_order,gate_name,passed,actual_value,threshold_value,reason_code",
        "stock_prediction_id.asc,gate_order.asc",
        {},
        signal,
      ),
      validationRun
        ? this.#all<ValidationMetricRow>("validation_fold_metrics", {
          select: "fold_number,metric_name,metric_value,metric_payload",
          validation_run_id: `eq.${validationRun.validation_run_id}`,
          order: "fold_number.asc,metric_name.asc",
        }, signal)
        : Promise.resolve([]),
      validationRun
        ? this.#select<BacktestRunRow>("backtest_runs", {
          select:
            "cost_scenario,cost_multiplier,status,summary_metrics,completed_at",
          validation_run_id: `eq.${validationRun.validation_run_id}`,
          order: "cost_multiplier.asc",
        }, signal)
        : Promise.resolve([]),
    ]);

    return {
      run,
      predictions,
      securities,
      currentSecurityHistory,
      audits,
      gates,
      markets,
      validationRun,
      validationMetrics,
      backtests,
      validationLinkStatus,
      calendarObservations: [] as TradingCalendarObservationRow[],
    };
  }

  async #selectIn<T extends JsonRecord>(
    table: string,
    column: string,
    ids: number[],
    select: string,
    order?: string,
    filters: Record<string, string> = {},
    signal?: AbortSignal,
  ): Promise<T[]> {
    const rows: T[] = [];
    for (let start = 0; start < ids.length; start += 100) {
      const values = ids.slice(start, start + 100);
      rows.push(
        ...await this.#select<T>(table, {
          select,
          [column]: `in.(${values.join(",")})`,
          ...filters,
          ...(order ? { order } : {}),
        }, signal),
      );
    }
    return rows;
  }

  async #all<T extends JsonRecord>(
    table: string,
    query: Record<string, string>,
    signal?: AbortSignal,
  ): Promise<T[]> {
    const rows: T[] = [];
    for (let offset = 0; offset < SELECT_LIMIT; offset += PAGE_SIZE) {
      const page = await this.#select<T>(table, {
        ...query,
        limit: String(PAGE_SIZE),
        offset: String(offset),
      }, signal);
      rows.push(...page);
      if (page.length < PAGE_SIZE) return rows;
    }
    throw new ApiError(
      409,
      "PREDICTION_SNAPSHOT_TOO_LARGE",
      "Snapshot exceeds the configured read limit",
    );
  }

  async #select<T extends JsonRecord>(
    table: string,
    query: Record<string, string>,
    parentSignal?: AbortSignal,
  ): Promise<T[]> {
    const url = new URL(`${this.#restUrl}/${table}`);
    for (const [name, value] of Object.entries(query)) {
      url.searchParams.set(name, value);
    }
    const fetchSignal = createTimedAbortSignal(
      parentSignal,
      this.#queryTimeoutMs,
    );
    try {
      const response = await this.fetchImpl(url, {
        method: "GET",
        headers: {
          Accept: "application/json",
          "Accept-Profile": "market_data",
          apikey: this.config.serviceRoleKey,
          Authorization: `Bearer ${this.config.serviceRoleKey}`,
        },
        cache: "no-store",
        signal: fetchSignal.signal,
      });
      if (!response.ok) {
        throw new ApiError(
          502,
          "PREDICTION_DATABASE_READ_FAILED",
          `Database read failed for ${table}`,
        );
      }
      const payload: unknown = await response.json();
      if (!Array.isArray(payload)) {
        throw new ApiError(
          502,
          "PREDICTION_DATABASE_RESPONSE_INVALID",
          `Database response is invalid for ${table}`,
        );
      }
      return payload as T[];
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (parentSignal?.aborted) {
        throw parentSignal.reason instanceof ApiError
          ? parentSignal.reason
          : new ApiError(
            504,
            "PREDICTION_REQUEST_TIMEOUT",
            "Prediction snapshot request exceeded its deadline",
          );
      }
      if (fetchSignal.timedOut()) {
        throw new ApiError(
          504,
          "PREDICTION_DATABASE_TIMEOUT",
          `Database read timed out for ${table}`,
        );
      }
      throw new ApiError(
        502,
        "PREDICTION_DATABASE_READ_FAILED",
        `Database read failed for ${table}`,
      );
    } finally {
      fetchSignal.cleanup();
    }
  }
}
