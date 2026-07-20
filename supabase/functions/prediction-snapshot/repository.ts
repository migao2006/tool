import { ApiError } from "./errors.ts";
import type {
  BacktestRunRow,
  DataQualityAuditRow,
  DecisionGateRow,
  JsonRecord,
  MarketPredictionRow,
  MarketScope,
  PredictionRunRow,
  SecurityRow,
  SecurityHistoryRow,
  SnapshotRepositoryContract,
  SnapshotRows,
  StockPredictionRow,
  ValidationMetricRow,
  ValidationRunRow,
} from "./types.ts";

const PAGE_SIZE = 1_000;
const SELECT_LIMIT = 5_000;

type FetchLike = typeof fetch;

export interface RepositoryConfig {
  supabaseUrl: string;
  serviceRoleKey: string;
}

export class SnapshotRepository implements SnapshotRepositoryContract {
  readonly #restUrl: string;

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
  }

  async loadLatest(
    horizon: number,
    marketScope: MarketScope,
  ): Promise<SnapshotRows | null> {
    const runs = await this.#select<PredictionRunRow>("prediction_runs", {
      select:
        "prediction_run_id,as_of_date,decision_at,horizon,market_scope,model_bundle_version,feature_schema_hash,cost_profile_version,training_end_date,system_validation_status,source_dates,latest_available_at,candidate_count,watch_count,no_trade_count,hard_fail_count,created_at",
      horizon: `eq.${horizon}`,
      market_scope: `eq.${marketScope}`,
      order: "decision_at.desc,prediction_run_id.desc",
      limit: "1",
    });
    const run = runs[0];
    if (!run) return null;

    const runId = Number(run.prediction_run_id);
    const [predictions, audits, markets, validationRuns] = await Promise.all([
      this.#all<StockPredictionRow>("stock_predictions", {
        select:
          "stock_prediction_id,prediction_run_id,security_id,market,industry,rank_score,global_rank,global_rank_percentile,industry_rank,industry_rank_percentile,calibrated_p_up,calibrated_p_neutral,calibrated_p_down,calibration_version,gross_q10,gross_q50,gross_q90,net_q10,net_q50,net_q90,interval_width,calibration_status,forecast_volatility,downside_risk,adv20_ntd,maximum_order_notional_ntd,market_regime,market_exposure_cap,estimated_round_trip_cost,data_quality_status,decision,reason_codes",
        prediction_run_id: `eq.${runId}`,
        order: "global_rank.asc",
      }),
      this.#all<DataQualityAuditRow>("data_quality_audits", {
        select:
          "security_id,quality_status,hard_fail,reason_codes,source_dates,latest_available_at",
        prediction_run_id: `eq.${runId}`,
        order: "security_id.asc",
      }),
      this.#select<MarketPredictionRow>("market_predictions", {
        select:
          "market,calibrated_p_up,calibrated_p_neutral,calibrated_p_down,market_regime,forecast_market_volatility,market_exposure_cap,model_version,training_end_date",
        prediction_run_id: `eq.${runId}`,
        order: "market.asc",
      }),
      this.#select<ValidationRunRow>("validation_runs", {
        select:
          "validation_run_id,validation_status,locked_holdout,frozen_config_hash,started_at,completed_at,limitations",
        model_bundle_version: `eq.${run.model_bundle_version}`,
        horizon: `eq.${horizon}`,
        completed_at: `lte.${run.created_at}`,
        order: "completed_at.desc.nullslast,validation_run_id.desc",
        limit: "2",
      }),
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
    const [securities, currentSecurityHistory, gates, validationMetrics, backtests] = await Promise.all(
      [
        this.#selectIn<SecurityRow>(
          "securities",
          "security_id",
          securityIds,
          "security_id,symbol,display_name,market,asset_type",
        ),
        this.#selectIn<SecurityHistoryRow>(
          "security_history",
          "security_id",
          securityIds,
          "security_id,effective_from,effective_to,industry_code,industry_name,source_version,available_at",
          "effective_from.desc,available_at.desc",
          { effective_to: "is.null" },
        ),
        this.#selectIn<DecisionGateRow>(
          "decision_gate_results",
          "stock_prediction_id",
          predictionIds,
          "stock_prediction_id,gate_order,gate_name,passed,actual_value,threshold_value,reason_code",
          "gate_order.asc",
        ),
        validationRun
          ? this.#all<ValidationMetricRow>("validation_fold_metrics", {
            select: "fold_number,metric_name,metric_value,metric_payload",
            validation_run_id: `eq.${validationRun.validation_run_id}`,
            order: "fold_number.asc,metric_name.asc",
          })
          : Promise.resolve([]),
        validationRun
          ? this.#select<BacktestRunRow>("backtest_runs", {
            select:
              "cost_scenario,cost_multiplier,status,summary_metrics,completed_at",
            validation_run_id: `eq.${validationRun.validation_run_id}`,
            order: "cost_multiplier.asc",
          })
          : Promise.resolve([]),
      ],
    );

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
    };
  }

  async #selectIn<T extends JsonRecord>(
    table: string,
    column: string,
    ids: number[],
    select: string,
    order?: string,
    filters: Record<string, string> = {},
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
        }),
      );
    }
    return rows;
  }

  async #all<T extends JsonRecord>(
    table: string,
    query: Record<string, string>,
  ): Promise<T[]> {
    const rows: T[] = [];
    for (let offset = 0; offset < SELECT_LIMIT; offset += PAGE_SIZE) {
      const page = await this.#select<T>(table, {
        ...query,
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
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
  ): Promise<T[]> {
    const url = new URL(`${this.#restUrl}/${table}`);
    for (const [name, value] of Object.entries(query)) {
      url.searchParams.set(name, value);
    }
    const response = await this.fetchImpl(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "Accept-Profile": "market_data",
        apikey: this.config.serviceRoleKey,
        Authorization: `Bearer ${this.config.serviceRoleKey}`,
      },
      cache: "no-store",
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
  }
}
