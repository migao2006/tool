-- Test-only seed for validating the forward migration on an isolated database.
-- Apply immediately before 20260724044115_decision_policy_status_semantics.sql.

insert into market_data.data_sources (
  source_code,
  display_name,
  source_timezone,
  revision_policy
)
values (
  'LEGACY_POLICY_BACKFILL_TEST',
  'Legacy policy backfill test',
  'Asia/Taipei',
  'IMMUTABLE_TEST'
);

insert into market_data.cost_profiles (
  cost_profile_version,
  asset_type,
  commission_rate,
  commission_discount,
  minimum_fee,
  sell_tax_rate,
  estimated_order_notional_ntd,
  spread_model,
  slippage_scenario,
  market_impact_parameter,
  max_adv_participation,
  parameters
)
values (
  'legacy-policy-backfill-test-v1',
  'COMMON_STOCK',
  0.001425,
  1,
  20,
  0.003,
  100000,
  'validation',
  'BASE',
  0.001,
  0.01,
  '{}'::jsonb
);

with source as (
  select source_id
  from market_data.data_sources
  where source_code = 'LEGACY_POLICY_BACKFILL_TEST'
)
insert into market_data.securities (
  symbol,
  display_name,
  market,
  asset_type,
  source_id
)
select
  row.symbol,
  row.display_name,
  'TWSE',
  'COMMON_STOCK',
  source.source_id
from source
cross join (
  values
    ('LDP1', 'Legacy warning marker row'),
    ('LDP2', 'Legacy audit warning row'),
    ('LDP3', 'Legacy audit hard fail row'),
    ('LDP4', 'Legacy unclassified policy row')
) as row(symbol, display_name);

with securities as (
  select security_id, symbol
  from market_data.securities
  where market = 'TWSE' and symbol in ('LDP1', 'LDP2', 'LDP3', 'LDP4')
),
run as (
  insert into market_data.prediction_runs (
    as_of_date,
    decision_at,
    horizon,
    market_scope,
    model_bundle_version,
    feature_schema_hash,
    benchmark_versions,
    cost_profile_version,
    training_end_date,
    system_validation_status,
    source_dates,
    latest_available_at,
    candidate_count,
    watch_count,
    no_trade_count,
    hard_fail_count
  )
  values (
    '2026-07-20',
    '2026-07-20T09:00:00+00:00',
    5,
    'TWSE',
    'legacy-decision-policy-backfill-test',
    repeat('f', 64),
    '{"TWSE":"validation-v1"}'::jsonb,
    'legacy-policy-backfill-test-v1',
    '2026-06-30',
    'RESEARCH_ONLY',
    '{"prediction_scope":"DAILY_RESEARCH_INFERENCE"}'::jsonb,
    '2026-07-20T08:30:00+00:00',
    0,
    0,
    4,
    1
  )
  returning prediction_run_id
)
insert into market_data.stock_predictions (
  prediction_run_id,
  security_id,
  market,
  industry,
  model_raw_score,
  rank_score,
  global_rank,
  global_rank_percentile,
  industry_rank,
  industry_rank_percentile,
  calibrated_p_up,
  calibrated_p_neutral,
  calibrated_p_down,
  calibration_version,
  gross_q10,
  gross_q50,
  gross_q90,
  net_q10,
  net_q50,
  net_q90,
  interval_width,
  quantile_crossing_before_calibration,
  calibration_status,
  estimated_round_trip_cost,
  data_quality_status,
  decision,
  reason_codes
)
select
  run.prediction_run_id,
  securities.security_id,
  'TWSE',
  'VALIDATION',
  0.8,
  case securities.symbol
    when 'LDP1' then 100
    when 'LDP2' then 50
    else 0
  end,
  case securities.symbol
    when 'LDP1' then 1
    when 'LDP2' then 2
    when 'LDP3' then 3
    else 4
  end,
  case securities.symbol
    when 'LDP1' then 1
    when 'LDP2' then 0.5
    else 0
  end,
  case securities.symbol
    when 'LDP1' then 1
    when 'LDP2' then 2
    when 'LDP3' then 3
    else 4
  end,
  case securities.symbol
    when 'LDP1' then 1
    when 'LDP2' then 0.5
    else 0
  end,
  0.6,
  0.3,
  0.1,
  'validation-v1',
  -0.02,
  0.01,
  0.05,
  -0.026,
  0.004,
  0.044,
  0.07,
  false,
  'CALIBRATED:validation-v1',
  0.006,
  case when securities.symbol in ('LDP3', 'LDP4') then 'PASS' else 'FAIL' end,
  'NO_TRADE',
  case securities.symbol
    when 'LDP1' then array[
      'RESEARCH_DATA_QUALITY_WARN',
      'FORMAL_MARKET_EXPOSURE_INPUT_MISSING'
    ]
    when 'LDP2' then array['FORMAL_MARKET_EXPOSURE_INPUT_MISSING']
    when 'LDP3' then '{}'::text[]
    else array['UNCLASSIFIED_LEGACY_POLICY_STATE']
  end
from securities
cross join run;

with run as (
  select prediction_run_id
  from market_data.prediction_runs
  where model_bundle_version = 'legacy-decision-policy-backfill-test'
),
securities as (
  select security_id, symbol
  from market_data.securities
  where market = 'TWSE' and symbol in ('LDP2', 'LDP3')
)
insert into market_data.data_quality_audits (
  prediction_run_id,
  security_id,
  quality_pass,
  completeness_score,
  freshness,
  quality_status,
  hard_fail,
  reason_codes,
  source_dates,
  latest_available_at
)
select
  run.prediction_run_id,
  securities.security_id,
  false,
  case when securities.symbol = 'LDP2' then 0.8 else 0.2 end,
  case when securities.symbol = 'LDP2' then 'FRESH' else 'STALE' end,
  'FAIL',
  securities.symbol = 'LDP3',
  case securities.symbol
    when 'LDP2' then array['AUDIT_NON_HARD_WARNING']
    else array['AUDIT_HARD_FAIL']
  end,
  '{"daily_bars":"2026-07-20"}'::jsonb,
  '2026-07-20T08:30:00+00:00'
from run
cross join securities;
