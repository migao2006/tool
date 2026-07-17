import {
  CURRENT_HORIZON,
  createResearchOnlySnapshot,
  isReleasedHorizon,
  normalizeHorizon,
} from "../core/five-day-contract.js";

/**
 * @typedef {Object} PredictionRecord
 * @property {string|null} as_of_date
 * @property {string|null} decision_at
 * @property {string} symbol
 * @property {string|null} name
 * @property {string} market
 * @property {string} industry
 * @property {number} horizon
 * @property {number|null} rank_score
 * @property {number|null} global_rank
 * @property {number|null} industry_rank
 * @property {number|null} calibrated_p_up
 * @property {number|null} calibrated_p_neutral
 * @property {number|null} calibrated_p_down
 * @property {number|null} net_q10
 * @property {number|null} net_q50
 * @property {number|null} net_q90
 * @property {number|null} estimated_round_trip_cost
 * @property {string} data_quality_status
 * @property {string} decision
 * @property {string[]} reason_codes
 */

export async function loadPredictionSnapshot({
  horizon = CURRENT_HORIZON,
} = {}) {
  const normalizedHorizon = normalizeHorizon(horizon);
  if (!isReleasedHorizon(normalizedHorizon)) {
    return createResearchOnlySnapshot(normalizedHorizon, "MODEL_NOT_RELEASED");
  }
  return createResearchOnlySnapshot(normalizedHorizon, "REAL_DATA_NOT_CONNECTED");
}
