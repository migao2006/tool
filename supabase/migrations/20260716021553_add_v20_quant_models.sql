-- Taiwan Stock Smart v20: additive quantitative read models and point-in-time
-- backtest storage. Existing v19 tables remain unchanged and authoritative.

create table if not exists public.v20_market_context (
  data_date date not null,
  model_version text not null default '20.0',
  regime text not null check (regime in ('strong_bull', 'bull', 'sideways', 'bear', 'strong_bear')),
  regime_score numeric not null check (regime_score between -100 and 100),
  confidence numeric not null default 0 check (confidence between 0 and 100),
  completeness numeric not null default 0 check (completeness between 0 and 100),
  status text not null default 'partial' check (status in ('complete', 'partial', 'error')),
  taiex jsonb not null default '{}'::jsonb,
  tpex jsonb not null default '{}'::jsonb,
  tx_futures jsonb not null default '{}'::jsonb,
  breadth jsonb not null default '{}'::jsonb,
  institutional jsonb not null default '{}'::jsonb,
  global_context jsonb not null default '{}'::jsonb,
  source_dates jsonb not null default '{}'::jsonb,
  degraded_sources text[] not null default '{}',
  fetched_at timestamptz,
  generated_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (data_date, model_version)
);

create index if not exists v20_market_context_latest_idx
  on public.v20_market_context (model_version, data_date desc)
  include (regime, regime_score, confidence, completeness, status);

create table if not exists public.v20_model_signals (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  signal_date date not null,
  model_key text not null check (model_key in ('short', 'medium')),
  horizon_days integer not null,
  model_version text not null default '20.0',
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  name text not null,
  market text,
  industry text,
  instrument_type text,
  strategy_key text not null,
  opportunity_score numeric not null check (opportunity_score between 0 and 100),
  risk_score numeric not null check (risk_score between 0 and 100),
  confidence numeric not null default 0 check (confidence between 0 and 100),
  completeness numeric not null default 0 check (completeness between 0 and 100),
  official boolean not null default false,
  gate_passed boolean not null default false,
  gate_results jsonb not null default '{}'::jsonb,
  feature_scores jsonb not null default '{}'::jsonb,
  prediction_basis text not null,
  up_probability numeric check (up_probability between 0 and 100),
  expected_return_net numeric,
  return_p10 numeric,
  return_p50 numeric,
  return_p90 numeric,
  mfe numeric,
  mae numeric,
  target_first_probability numeric check (target_first_probability between 0 and 100),
  entry_low numeric,
  entry_high numeric,
  breakout_price numeric,
  no_chase_price numeric,
  stop_loss numeric,
  take_profit_1 numeric,
  take_profit_2 numeric,
  risk_reward_ratio numeric,
  expected_value numeric,
  recommended_holding_days integer check (recommended_holding_days > 0),
  recommended_action text not null,
  reasons jsonb not null default '[]'::jsonb,
  risks jsonb not null default '[]'::jsonb,
  invalidation_conditions jsonb not null default '[]'::jsonb,
  source_dates jsonb not null default '{}'::jsonb,
  generated_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (symbol, signal_date, model_key, horizon_days, model_version),
  check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (20, 40, 60))
  )
);

create index if not exists v20_model_signals_rank_idx
  on public.v20_model_signals
    (model_key, horizon_days, model_version, signal_date desc, official, opportunity_score desc, expected_value desc nulls last)
  include (symbol, group_name, risk_score, confidence, completeness, strategy_key);
create index if not exists v20_model_signals_group_rank_idx
  on public.v20_model_signals
    (model_key, horizon_days, group_name, model_version, signal_date desc, opportunity_score desc)
  where official and gate_passed;
create index if not exists v20_model_signals_industry_rank_idx
  on public.v20_model_signals
    (model_key, horizon_days, lower(industry), model_version, signal_date desc, opportunity_score desc)
  where official and gate_passed;
create index if not exists v20_model_signals_symbol_history_idx
  on public.v20_model_signals (symbol, model_key, model_version, signal_date desc, horizon_days);

create table if not exists public.v20_ranking_snapshots (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  ranking_date date not null,
  model_key text not null check (model_key in ('short', 'medium')),
  horizon_days integer not null,
  model_version text not null default '20.0',
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  name text not null,
  market text,
  industry text,
  instrument_type text,
  strategy_key text not null,
  rank_position integer not null check (rank_position > 0),
  previous_rank integer check (previous_rank > 0),
  rank_delta integer,
  opportunity_score numeric not null check (opportunity_score between 0 and 100),
  risk_score numeric not null check (risk_score between 0 and 100),
  confidence numeric not null default 0 check (confidence between 0 and 100),
  completeness numeric not null default 0 check (completeness between 0 and 100),
  expected_value numeric,
  prediction_basis text not null,
  up_probability numeric check (up_probability between 0 and 100),
  expected_return_net numeric,
  recommended_action text not null,
  summary text,
  official boolean not null default true,
  generated_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (symbol, ranking_date, model_key, horizon_days, model_version),
  foreign key (symbol, ranking_date, model_key, horizon_days, model_version)
    references public.v20_model_signals(symbol, signal_date, model_key, horizon_days, model_version)
    on delete cascade,
  check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (20, 40, 60))
  )
);

create unique index if not exists v20_ranking_snapshots_position_uidx
  on public.v20_ranking_snapshots
    (ranking_date, model_key, horizon_days, model_version, rank_position);
create index if not exists v20_ranking_snapshots_page_idx
  on public.v20_ranking_snapshots
    (model_key, horizon_days, model_version, ranking_date desc, rank_position)
  include (symbol, group_name, strategy_key, opportunity_score, risk_score, confidence);
create index if not exists v20_ranking_snapshots_group_page_idx
  on public.v20_ranking_snapshots
    (model_key, horizon_days, group_name, model_version, ranking_date desc, rank_position);
create index if not exists v20_ranking_snapshots_industry_page_idx
  on public.v20_ranking_snapshots
    (model_key, horizon_days, lower(industry), model_version, ranking_date desc, rank_position);

create table if not exists public.v20_universe_membership (
  symbol text not null references public.stock_master(symbol) on delete cascade,
  as_of_date date not null,
  model_version text not null default '20.0',
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  name text not null,
  market text,
  industry text,
  instrument_type text,
  active boolean not null default true,
  eligible_short boolean not null default false,
  eligible_medium boolean not null default false,
  inclusion_reasons jsonb not null default '[]'::jsonb,
  exclusion_reasons jsonb not null default '[]'::jsonb,
  source_dates jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default clock_timestamp(),
  primary key (symbol, as_of_date, model_version)
);

create index if not exists v20_universe_membership_cycle_idx
  on public.v20_universe_membership (model_version, as_of_date desc, group_name, symbol);
create index if not exists v20_universe_membership_short_idx
  on public.v20_universe_membership (model_version, as_of_date desc, group_name, symbol)
  where active and eligible_short;
create index if not exists v20_universe_membership_medium_idx
  on public.v20_universe_membership (model_version, as_of_date desc, group_name, symbol)
  where active and eligible_medium;

create table if not exists public.v20_backtest_runs (
  id bigint generated always as identity primary key,
  model_key text not null check (model_key in ('short', 'medium')),
  model_version text not null default '20.0',
  strategy_key text not null default 'all',
  horizon_days integer not null,
  training_start date not null,
  training_end date not null,
  test_start date not null,
  test_end date not null,
  universe_as_of date not null,
  market_regime text not null default 'all',
  status text not null default 'pending' check (status in ('pending', 'running', 'complete', 'partial', 'error')),
  configuration jsonb not null default '{}'::jsonb,
  sample_count integer not null default 0 check (sample_count >= 0),
  metrics jsonb not null default '{}'::jsonb,
  error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  check (training_start <= training_end and training_end < test_start and test_start <= test_end),
  check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (20, 40, 60))
  )
);

create unique index if not exists v20_backtest_runs_window_uidx
  on public.v20_backtest_runs
    (model_key, model_version, strategy_key, horizon_days, training_start, training_end, test_start, test_end, universe_as_of, market_regime);
create index if not exists v20_backtest_runs_status_idx
  on public.v20_backtest_runs (status, model_key, model_version, created_at)
  where status in ('pending', 'running', 'partial', 'error');
create index if not exists v20_backtest_runs_complete_idx
  on public.v20_backtest_runs (model_key, horizon_days, model_version, completed_at desc)
  where status = 'complete';

create table if not exists public.v20_backtest_outcomes (
  run_id bigint not null references public.v20_backtest_runs(id) on delete cascade,
  symbol text not null references public.stock_master(symbol) on delete cascade,
  signal_date date not null,
  model_key text not null check (model_key in ('short', 'medium')),
  model_version text not null default '20.0',
  strategy_key text not null,
  horizon_days integer not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  industry text,
  market_regime text not null,
  score_decile smallint check (score_decile between 0 and 9),
  opportunity_score numeric not null check (opportunity_score between 0 and 100),
  risk_score numeric not null check (risk_score between 0 and 100),
  confidence numeric not null default 0 check (confidence between 0 and 100),
  up_probability numeric check (up_probability between 0 and 100),
  expected_return_net numeric,
  entry_date date not null,
  entry_price numeric not null check (entry_price > 0),
  exit_date date,
  exit_price numeric check (exit_price > 0),
  gross_return numeric,
  net_return numeric,
  mfe numeric,
  mae numeric,
  target_hit_first boolean,
  transaction_cost numeric not null default 0 check (transaction_cost >= 0),
  slippage_cost numeric not null default 0 check (slippage_cost >= 0),
  evaluated_at timestamptz,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (run_id, symbol, signal_date, horizon_days)
);

create index if not exists v20_backtest_outcomes_symbol_idx
  on public.v20_backtest_outcomes (symbol, model_key, model_version, signal_date desc, horizon_days);
create index if not exists v20_backtest_outcomes_bucket_idx
  on public.v20_backtest_outcomes
    (model_key, model_version, horizon_days, strategy_key, market_regime, score_decile)
  include (net_return, mfe, mae, up_probability, target_hit_first);
create index if not exists v20_backtest_outcomes_industry_idx
  on public.v20_backtest_outcomes
    (model_key, model_version, horizon_days, lower(industry), signal_date desc);

create table if not exists public.v20_calibration_buckets (
  model_key text not null check (model_key in ('short', 'medium')),
  model_version text not null default '20.0',
  strategy_key text not null default 'all',
  horizon_days integer not null,
  market_regime text not null default 'all',
  score_decile smallint not null default -1 check (score_decile between -1 and 9),
  sample_count integer not null default 0 check (sample_count >= 0),
  wins integer not null default 0 check (wins >= 0 and wins <= sample_count),
  raw_probability numeric check (raw_probability between 0 and 100),
  calibrated_probability numeric check (calibrated_probability between 0 and 100),
  average_net_return numeric,
  return_p10 numeric,
  return_p50 numeric,
  return_p90 numeric,
  average_mfe numeric,
  average_mae numeric,
  target_first_probability numeric check (target_first_probability between 0 and 100),
  calibration_error numeric check (calibration_error >= 0),
  training_start date not null,
  training_end date not null,
  calibration_date date not null,
  generated_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (model_key, model_version, strategy_key, horizon_days, market_regime, score_decile),
  check (training_start <= training_end),
  check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (20, 40, 60))
  )
);

create index if not exists v20_calibration_buckets_lookup_idx
  on public.v20_calibration_buckets
    (model_key, model_version, horizon_days, strategy_key, market_regime, score_decile, calibration_date desc);

-- The public API can only see completed, gate-passing read models. Internal
-- universe/backtest/calibration rows have RLS enabled with no client policy.
alter table public.v20_market_context enable row level security;
alter table public.v20_model_signals enable row level security;
alter table public.v20_ranking_snapshots enable row level security;
alter table public.v20_universe_membership enable row level security;
alter table public.v20_backtest_runs enable row level security;
alter table public.v20_backtest_outcomes enable row level security;
alter table public.v20_calibration_buckets enable row level security;

drop policy if exists v20_market_context_public_read on public.v20_market_context;
create policy v20_market_context_public_read on public.v20_market_context
  for select to anon, authenticated
  using (status in ('complete', 'partial'));

drop policy if exists v20_model_signals_public_read on public.v20_model_signals;
create policy v20_model_signals_public_read on public.v20_model_signals
  for select to anon, authenticated
  using (official and gate_passed);

drop policy if exists v20_ranking_snapshots_public_read on public.v20_ranking_snapshots;
create policy v20_ranking_snapshots_public_read on public.v20_ranking_snapshots
  for select to anon, authenticated
  using (official);

revoke all on table
  public.v20_market_context,
  public.v20_model_signals,
  public.v20_ranking_snapshots,
  public.v20_universe_membership,
  public.v20_backtest_runs,
  public.v20_backtest_outcomes,
  public.v20_calibration_buckets
from public, anon, authenticated;

grant select on table
  public.v20_market_context,
  public.v20_model_signals,
  public.v20_ranking_snapshots
to anon, authenticated, service_role;

grant all on table
  public.v20_market_context,
  public.v20_model_signals,
  public.v20_ranking_snapshots,
  public.v20_universe_membership,
  public.v20_backtest_runs,
  public.v20_backtest_outcomes,
  public.v20_calibration_buckets
to service_role;

revoke all on sequence public.v20_backtest_runs_id_seq from public, anon, authenticated;
grant usage, select on sequence public.v20_backtest_runs_id_seq to service_role;

-- Reuse the existing trigger helper without changing any legacy table.
drop trigger if exists v20_market_context_set_updated_at on public.v20_market_context;
create trigger v20_market_context_set_updated_at before update on public.v20_market_context
for each row execute function public.set_updated_at();
drop trigger if exists v20_model_signals_set_updated_at on public.v20_model_signals;
create trigger v20_model_signals_set_updated_at before update on public.v20_model_signals
for each row execute function public.set_updated_at();
drop trigger if exists v20_ranking_snapshots_set_updated_at on public.v20_ranking_snapshots;
create trigger v20_ranking_snapshots_set_updated_at before update on public.v20_ranking_snapshots
for each row execute function public.set_updated_at();
drop trigger if exists v20_universe_membership_set_updated_at on public.v20_universe_membership;
create trigger v20_universe_membership_set_updated_at before update on public.v20_universe_membership
for each row execute function public.set_updated_at();
drop trigger if exists v20_backtest_runs_set_updated_at on public.v20_backtest_runs;
create trigger v20_backtest_runs_set_updated_at before update on public.v20_backtest_runs
for each row execute function public.set_updated_at();
drop trigger if exists v20_backtest_outcomes_set_updated_at on public.v20_backtest_outcomes;
create trigger v20_backtest_outcomes_set_updated_at before update on public.v20_backtest_outcomes
for each row execute function public.set_updated_at();
drop trigger if exists v20_calibration_buckets_set_updated_at on public.v20_calibration_buckets;
create trigger v20_calibration_buckets_set_updated_at before update on public.v20_calibration_buckets
for each row execute function public.set_updated_at();

-- Atomically rebuild the public ranking snapshot after an idempotent signal
-- batch completes. The function is service-only and serializes by date/version.
create or replace function public.twss_v20_refresh_rankings(
  p_ranking_date date,
  p_model_version text default '20.0'
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_rows integer := 0;
begin
  if p_ranking_date is null
    or nullif(pg_catalog.btrim(coalesce(p_model_version, '')), '') is null
  then
    raise exception 'v20_invalid_ranking_cycle';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-ranking:' || p_ranking_date::text || ':' || p_model_version, 0)
  );

  delete from public.v20_ranking_snapshots
  where ranking_date = p_ranking_date and model_version = p_model_version;

  with previous_dates as (
    select model_key, horizon_days, max(ranking_date) as ranking_date
    from public.v20_ranking_snapshots
    where model_version = p_model_version and ranking_date < p_ranking_date
    group by model_key, horizon_days
  ), previous as (
    select r.symbol, r.model_key, r.horizon_days, r.rank_position
    from public.v20_ranking_snapshots r
    join previous_dates d using (model_key, horizon_days, ranking_date)
    where r.model_version = p_model_version
  ), ranked as (
    select
      s.*,
      row_number() over (
        partition by s.model_key, s.horizon_days
        order by s.expected_value desc nulls last,
          s.opportunity_score desc, s.risk_score asc, s.confidence desc, s.symbol
      )::integer as rank_position
    from public.v20_model_signals s
    where s.signal_date = p_ranking_date
      and s.model_version = p_model_version
      and s.official
      and s.gate_passed
  )
  insert into public.v20_ranking_snapshots (
    symbol, ranking_date, model_key, horizon_days, model_version,
    group_name, name, market, industry, instrument_type, strategy_key,
    rank_position, previous_rank, rank_delta, opportunity_score, risk_score,
    confidence, completeness, expected_value, prediction_basis, up_probability,
    expected_return_net, recommended_action, summary, official,
    generated_at, updated_at
  )
  select
    r.symbol, r.signal_date, r.model_key, r.horizon_days, r.model_version,
    r.group_name, r.name, r.market, r.industry, r.instrument_type, r.strategy_key,
    r.rank_position, p.rank_position,
    case when p.rank_position is null then null else p.rank_position - r.rank_position end,
    r.opportunity_score, r.risk_score, r.confidence, r.completeness,
    r.expected_value, r.prediction_basis, r.up_probability, r.expected_return_net,
    r.recommended_action,
    coalesce(r.reasons ->> 0, r.recommended_action), true,
    clock_timestamp(), clock_timestamp()
  from ranked r
  left join previous p
    on p.symbol = r.symbol
    and p.model_key = r.model_key
    and p.horizon_days = r.horizon_days;

  get diagnostics v_rows = row_count;
  return pg_catalog.jsonb_build_object(
    'rankingDate', p_ranking_date,
    'modelVersion', p_model_version,
    'rows', v_rows,
    'generatedAt', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_v20_refresh_rankings(date, text)
  from public, anon, authenticated;
grant execute on function public.twss_v20_refresh_rankings(date, text) to service_role;

-- Safe aggregate for the Vercel read API. It intentionally exposes no signal,
-- account, calibration-bucket, or per-trade outcome row.
create or replace function public.twss_v20_public_backtest_summary(
  p_model_key text default null,
  p_horizon_days integer default null,
  p_strategy_key text default null,
  p_regime text default null,
  p_industry text default null
)
returns table (
  model_key text,
  horizon_days integer,
  strategy_key text,
  regime text,
  industry text,
  sample_count bigint,
  win_rate numeric,
  average_net_return numeric,
  median_net_return numeric,
  average_mfe numeric,
  average_mae numeric,
  calibration_error numeric,
  generated_at timestamptz
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    o.model_key,
    o.horizon_days,
    o.strategy_key,
    o.market_regime as regime,
    coalesce(o.industry, 'unknown') as industry,
    count(*)::bigint as sample_count,
    round(100 * avg(case when o.net_return > 0 then 1 else 0 end)::numeric, 2) as win_rate,
    round(avg(o.net_return)::numeric, 4) as average_net_return,
    round((pg_catalog.percentile_cont(0.5) within group (order by o.net_return))::numeric, 4) as median_net_return,
    round(avg(o.mfe)::numeric, 4) as average_mfe,
    round(avg(o.mae)::numeric, 4) as average_mae,
    round((100 * avg(
      abs((o.up_probability / 100) - case when o.net_return > 0 then 1 else 0 end)
    ) filter (where o.up_probability is not null))::numeric, 4) as calibration_error,
    max(coalesce(o.evaluated_at, r.completed_at, o.created_at)) as generated_at
  from public.v20_backtest_outcomes o
  join public.v20_backtest_runs r on r.id = o.run_id and r.status = 'complete'
  where (p_model_key is null or o.model_key = p_model_key)
    and (p_horizon_days is null or o.horizon_days = p_horizon_days)
    and (p_strategy_key is null or o.strategy_key = p_strategy_key)
    and (p_regime is null or o.market_regime = p_regime)
    and (p_industry is null or coalesce(o.industry, 'unknown') = p_industry)
  group by o.model_key, o.horizon_days, o.strategy_key, o.market_regime, coalesce(o.industry, 'unknown')
  order by sample_count desc, o.model_key, o.horizon_days, o.strategy_key
  limit 500;
$$;

revoke all on function public.twss_v20_public_backtest_summary(text, integer, text, text, text)
  from public, anon, authenticated;
grant execute on function public.twss_v20_public_backtest_summary(text, integer, text, text, text)
  to anon, authenticated, service_role;

insert into public.stock_sync_state (job_key, group_name, details)
values (
  'v20_model',
  null,
  '{"modelVersion":"20.0","scheduler":"pg_cron","retryPolicy":{"maxAttempts":3,"maxQueue":300,"retryShare":"25%-capped-at-10"}}'::jsonb
)
on conflict (job_key) do nothing;

-- Bounded weekday batches begin after the Taiwan cash close. A completedCycleKey
-- makes later invocations no-ops, while 10-minute retries let one failed symbol
-- remain isolated without blocking the daily universe. pg_cron uses UTC.
do $$
declare
  existing_job bigint;
begin
  for existing_job in
    select jobid from cron.job where jobname = 'twss-v20-model-weekday'
  loop
    perform cron.unschedule(existing_job);
  end loop;
end
$$;

select cron.schedule(
  'twss-v20-model-weekday',
  '*/10 7-10 * * 1-5',
  $job$
    select net.http_post(
      url := 'https://lfkdkdyaatdlizryiyon.supabase.co/functions/v1/twss-v20-model',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-twss-sync-token', (
          select decrypted_secret
          from vault.decrypted_secrets
          where name = 'twss_sync_token'
        )
      ),
      body := '{"limit":100}'::jsonb,
      timeout_milliseconds := 300000
    );
  $job$
);

comment on table public.v20_model_signals is
  'Independent short/medium v20 quantitative signals. Probabilities are deterministic or calibrated; never language-model generated.';
comment on table public.v20_backtest_outcomes is
  'Point-in-time walk-forward outcomes. Server-only; never directly exposed through the Data API.';
comment on function public.twss_v20_public_backtest_summary(text, integer, text, text, text) is
  'Audited SECURITY DEFINER boundary: fixed aggregate SQL, no dynamic SQL or user data, capped at 500 buckets, and never returns per-trade outcomes.';
