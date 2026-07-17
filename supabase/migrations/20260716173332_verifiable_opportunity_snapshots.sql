-- Taiwan Stock Smart v20.1: verifiable, immutable point-in-time publication.
--
-- The mutable v20_model_signals/v20_ranking_snapshots tables remain staging
-- tables for the worker.  A recommendation is public only after this migration's
-- single transactional publisher has copied a complete cycle into append-only
-- runs/items and advanced the publication head in the same transaction.

-- New scoring/cost fields are nullable on the legacy staging table so existing
-- 20.0 rows remain valid.  The v20.1 publisher below rejects any cycle whose
-- rows do not contain the complete v20.1 contract.
alter table public.v20_model_signals
  add column if not exists raw_opportunity_score numeric,
  add column if not exists net_opportunity_score numeric,
  add column if not exists estimated_commission_pct numeric,
  add column if not exists estimated_tax_pct numeric,
  add column if not exists estimated_slippage_pct numeric,
  add column if not exists estimated_spread_pct numeric,
  add column if not exists estimated_total_cost_pct numeric,
  add column if not exists downside_penalty_score numeric,
  add column if not exists turnover_penalty_score numeric,
  add column if not exists cost_penalty_score numeric,
  add column if not exists turnover_exposure numeric,
  add column if not exists liquidity_grade text,
  add column if not exists calibration_version text,
  add column if not exists calibration_sample_count integer,
  add column if not exists expected_excess_return_gross numeric,
  add column if not exists expected_excess_return_net numeric,
  add column if not exists benchmark_key text,
  add column if not exists research_only boolean not null default false;

do $$
declare
  v_table regclass;
  v_constraint record;
begin
  foreach v_table in array array[
    'public.v20_model_signals'::regclass,
    'public.v20_ranking_snapshots'::regclass,
    'public.v20_backtest_runs'::regclass,
    'public.v20_calibration_buckets'::regclass,
    'public.v20_signal_outcomes'::regclass
  ]
  loop
    for v_constraint in
      select c.conname
      from pg_catalog.pg_constraint c
      where c.conrelid = v_table
        and c.contype = 'c'
        and pg_catalog.pg_get_constraintdef(c.oid) like '%model_key%'
        and pg_catalog.pg_get_constraintdef(c.oid) like '%horizon_days%'
    loop
      execute pg_catalog.format(
        'alter table %s drop constraint %I',
        v_table,
        v_constraint.conname
      );
    end loop;
  end loop;
end
$$;

alter table public.v20_model_signals
  add constraint v20_model_signals_horizon_v21_check check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (10, 20, 40, 60))
  );
alter table public.v20_ranking_snapshots
  add constraint v20_ranking_snapshots_horizon_v21_check check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (10, 20, 40, 60))
  );
alter table public.v20_backtest_runs
  add constraint v20_backtest_runs_horizon_v21_check check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (10, 20, 40, 60))
  );
alter table public.v20_calibration_buckets
  add constraint v20_calibration_buckets_horizon_v21_check check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (10, 20, 40, 60))
  );
alter table public.v20_signal_outcomes
  add constraint v20_signal_outcomes_horizon_v21_check check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10))
    or (model_key = 'medium' and horizon_days in (10, 20, 40, 60))
  );

do $$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.v20_backtest_outcomes'::regclass
      and conname = 'v20_backtest_outcomes_horizon_v21_check'
  ) then
    alter table public.v20_backtest_outcomes
      add constraint v20_backtest_outcomes_horizon_v21_check check (
        (model_key = 'short' and horizon_days in (2, 3, 5, 10))
        or (model_key = 'medium' and horizon_days in (10, 20, 40, 60))
      ) not valid;
  end if;
end
$$;

do $$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.v20_model_signals'::regclass
      and conname = 'v20_model_signals_v21_scores_check'
  ) then
    alter table public.v20_model_signals
      add constraint v20_model_signals_v21_scores_check check (
        (raw_opportunity_score is null or raw_opportunity_score between 0 and 100)
        and (net_opportunity_score is null or net_opportunity_score between 0 and 100)
        and (downside_penalty_score is null or downside_penalty_score between 0 and 100)
        and (turnover_penalty_score is null or turnover_penalty_score between 0 and 100)
        and (cost_penalty_score is null or cost_penalty_score between 0 and 100)
        and (turnover_exposure is null or turnover_exposure between 0 and 4)
        and (
          calibration_version is null
          or calibration_version ~ '^twss-cal-sha256-[0-9a-f]{64}$'
        )
        and (calibration_sample_count is null or calibration_sample_count >= 0)
      ) not valid;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.v20_model_signals'::regclass
      and conname = 'v20_model_signals_v21_costs_check'
  ) then
    alter table public.v20_model_signals
      add constraint v20_model_signals_v21_costs_check check (
        (estimated_commission_pct is null or estimated_commission_pct >= 0)
        and (estimated_tax_pct is null or estimated_tax_pct >= 0)
        and (estimated_slippage_pct is null or estimated_slippage_pct >= 0)
        and (estimated_spread_pct is null or estimated_spread_pct >= 0)
        and (estimated_total_cost_pct is null or estimated_total_cost_pct >= 0)
      ) not valid;
  end if;
end
$$;

-- Raw staging tables and the old SELECT s.* RPC are no longer browser-facing.
drop policy if exists v20_model_signals_public_read on public.v20_model_signals;
drop policy if exists v20_ranking_snapshots_public_read on public.v20_ranking_snapshots;
revoke all on table public.v20_model_signals, public.v20_ranking_snapshots
  from public, anon, authenticated, service_role;
grant select, insert, update, delete on table
  public.v20_model_signals, public.v20_ranking_snapshots
  to service_role;

revoke all on function public.twss_v20_public_stock_signals(text, text)
  from public, anon, authenticated, service_role;
revoke all on function public.twss_v20_public_backtest_summary(text, integer, text, text, text)
  from public, anon, authenticated;
revoke all on function public.twss_v20_public_backtest_summary_v20(text, integer, text, text, text)
  from public, anon, authenticated;
revoke all on function public.twss_v20_publication_state()
  from public, anon, authenticated;

-- Deny-by-default for all future public-schema objects created by either
-- migration owner.  Every later migration must grant only the required verbs.
alter default privileges for role postgres in schema public
  revoke all on tables from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke all on sequences from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated, service_role;
-- Hosted Supabase's postgres role is not normally a member of supabase_admin.
-- Avoid making the migration undeployable; harden that owner's defaults only
-- in environments where the executing role can legally alter them.  Current
-- objects below are explicitly revoked regardless of this branch.
do $$
begin
  if pg_catalog.pg_has_role(current_user, 'supabase_admin', 'USAGE') then
    execute 'alter default privileges for role supabase_admin in schema public revoke all on tables from public, anon, authenticated, service_role';
    execute 'alter default privileges for role supabase_admin in schema public revoke all on sequences from public, anon, authenticated, service_role';
    execute 'alter default privileges for role supabase_admin in schema public revoke execute on functions from public, anon, authenticated, service_role';
  else
    raise warning 'v20_supabase_admin_default_acl_requires_platform_owner';
  end if;
end
$$;

create table if not exists public.v20_model_releases (
  id bigint generated always as identity primary key,
  model_key text not null check (model_key in ('short', 'medium')),
  model_version text not null,
  artifact_hash text not null check (artifact_hash ~ '^[0-9A-Fa-f]{7,128}$'),
  feature_version text not null,
  cost_model_version text not null,
  calibration_version text,
  validation_status text not null default 'shadow'
    check (validation_status in ('shadow', 'passed', 'failed')),
  configuration jsonb not null default '{}'::jsonb
    check (pg_catalog.jsonb_typeof(configuration) = 'object'),
  validation_metrics jsonb not null default '{}'::jsonb
    check (pg_catalog.jsonb_typeof(validation_metrics) = 'object'),
  registered_by text not null default 'service_role',
  registered_at timestamptz not null default clock_timestamp(),
  unique (model_key, model_version, artifact_hash)
);

create table if not exists public.v20_model_channel_events (
  id bigint generated always as identity primary key,
  model_key text not null check (model_key in ('short', 'medium')),
  channel text not null check (channel in ('champion', 'challenger')),
  release_id bigint not null references public.v20_model_releases(id) on delete restrict,
  previous_release_id bigint references public.v20_model_releases(id) on delete restrict,
  reason text not null,
  changed_by text not null default 'service_role',
  changed_at timestamptz not null default clock_timestamp()
);

create table if not exists public.v20_model_validation_events (
  id bigint generated always as identity primary key,
  release_id bigint not null references public.v20_model_releases(id) on delete restrict,
  validation_status text not null check (validation_status in ('shadow', 'passed', 'failed')),
  validation_metrics jsonb not null default '{}'::jsonb
    check (pg_catalog.jsonb_typeof(validation_metrics) = 'object'),
  window_start date,
  window_end date,
  notes text,
  recorded_by text not null default 'service_role',
  recorded_at timestamptz not null default clock_timestamp(),
  check (window_start is null or window_end is null or window_start <= window_end)
);

create table if not exists public.v20_model_channel_heads (
  model_key text not null check (model_key in ('short', 'medium')),
  channel text not null check (channel in ('champion', 'challenger')),
  release_id bigint not null references public.v20_model_releases(id) on delete restrict,
  event_id bigint not null references public.v20_model_channel_events(id) on delete restrict,
  changed_at timestamptz not null,
  primary key (model_key, channel),
  unique (model_key, release_id)
);

create table if not exists public.v20_recommendation_runs (
  id bigint generated always as identity primary key,
  publication_key text not null unique
    check (publication_key ~ '^[0-9a-f]{64}$'),
  data_date date not null,
  data_cutoff_at timestamptz not null,
  revision integer not null check (revision > 0),
  status text not null default 'published' check (status = 'published'),
  model_version text not null,
  feature_version text not null,
  cost_model_version text not null,
  calibration_version text,
  code_hash text not null check (code_hash ~ '^[0-9A-Za-z._-]{7,128}$'),
  source_version text not null,
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  source_manifest jsonb not null
    check (pg_catalog.jsonb_typeof(source_manifest) = 'object'),
  model_manifest jsonb not null default '{}'::jsonb
    check (pg_catalog.jsonb_typeof(model_manifest) = 'object'),
  market_context_snapshot jsonb not null
    check (
      pg_catalog.jsonb_typeof(market_context_snapshot) = 'object'
      and market_context_snapshot <> '{}'::jsonb
    ),
  market_regime text,
  expected_symbol_count integer not null check (expected_symbol_count > 0),
  scored_symbol_count integer not null check (scored_symbol_count = expected_symbol_count),
  signal_count integer not null check (signal_count = expected_symbol_count * 8),
  eligible_item_count integer not null check (eligible_item_count >= 0),
  research_item_count integer not null check (research_item_count = expected_symbol_count),
  cycle_completeness numeric not null check (cycle_completeness = 100),
  deadletter_count integer not null default 0 check (deadletter_count = 0),
  terminal_errors jsonb not null default '[]'::jsonb
    check (
      pg_catalog.jsonb_typeof(terminal_errors) = 'array'
      and pg_catalog.jsonb_array_length(terminal_errors) = 0
    ),
  content_hash text not null unique check (content_hash ~ '^[0-9a-f]{64}$'),
  published_by text not null default 'service_role',
  published_at timestamptz not null default clock_timestamp(),
  created_at timestamptz not null default clock_timestamp(),
  unique (data_date, model_version, revision),
  unique (id, publication_key),
  unique (id, content_hash)
);

create table if not exists public.v20_recommendation_items (
  id bigint generated always as identity primary key,
  run_id bigint not null,
  symbol text not null references public.stock_master(symbol) on delete restrict,
  signal_date date not null,
  model_key text not null check (model_key in ('short', 'medium')),
  horizon_days integer not null,
  model_version text not null,
  group_name text not null check (group_name in ('listed', 'otc', 'etf')),
  name text not null,
  market text,
  industry text,
  instrument_type text,
  strategy_key text not null,
  is_eligible boolean not null,
  public_visible boolean not null,
  research_only boolean not null,
  rank_position integer check (rank_position > 0),
  previous_rank integer check (previous_rank > 0),
  rank_delta integer,
  market_percentile numeric check (market_percentile between 0 and 100),
  raw_opportunity_score numeric not null check (raw_opportunity_score between 0 and 100),
  net_opportunity_score numeric not null check (net_opportunity_score between 0 and 100),
  risk_score numeric not null check (risk_score between 0 and 100),
  confidence numeric not null check (confidence between 0 and 100),
  completeness numeric not null check (completeness between 0 and 100),
  estimated_commission_pct numeric not null check (estimated_commission_pct >= 0),
  estimated_tax_pct numeric not null check (estimated_tax_pct >= 0),
  estimated_slippage_pct numeric not null check (estimated_slippage_pct >= 0),
  estimated_spread_pct numeric not null check (estimated_spread_pct >= 0),
  estimated_total_cost_pct numeric not null check (estimated_total_cost_pct >= 0),
  downside_penalty_score numeric not null check (downside_penalty_score between 0 and 100),
  turnover_penalty_score numeric not null check (turnover_penalty_score between 0 and 100),
  cost_penalty_score numeric not null check (cost_penalty_score between 0 and 100),
  turnover_exposure numeric not null check (turnover_exposure between 0 and 4),
  liquidity_grade text not null,
  opportunity_state text not null,
  prediction_basis text not null,
  calibrated_up_probability numeric check (calibrated_up_probability between 0 and 100),
  expected_return_net numeric,
  expected_excess_return_gross numeric,
  expected_excess_return_net numeric,
  calibration_sample_count integer check (calibration_sample_count >= 0),
  benchmark_key text,
  recommended_holding_days integer not null check (recommended_holding_days > 0),
  recommended_action text not null,
  entry_low numeric,
  entry_high numeric,
  breakout_price numeric,
  no_chase_price numeric,
  stop_loss numeric,
  take_profit_1 numeric,
  take_profit_2 numeric,
  risk_reward_ratio numeric,
  feature_scores jsonb not null check (pg_catalog.jsonb_typeof(feature_scores) = 'object'),
  gate_results jsonb not null check (pg_catalog.jsonb_typeof(gate_results) = 'object'),
  reasons jsonb not null check (pg_catalog.jsonb_typeof(reasons) = 'array'),
  risks jsonb not null check (pg_catalog.jsonb_typeof(risks) = 'array'),
  invalidation_conditions jsonb not null
    check (pg_catalog.jsonb_typeof(invalidation_conditions) = 'array'),
  source_manifest jsonb not null check (pg_catalog.jsonb_typeof(source_manifest) = 'object'),
  input_hash text not null check (input_hash ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default clock_timestamp(),
  unique (run_id, symbol, model_key, horizon_days),
  check (
    (model_key = 'short' and horizon_days in (2, 3, 5, 10) and not research_only)
    or (model_key = 'medium' and horizon_days in (10, 20, 40) and not research_only)
    or (model_key = 'medium' and horizon_days = 60 and research_only)
  ),
  check (public_visible = not research_only),
  check (
    (is_eligible and rank_position is not null and market_percentile is not null)
    or (not is_eligible and rank_position is null and market_percentile is null)
  )
);

create table if not exists public.v20_publication_head (
  audience text primary key check (audience = 'public'),
  run_id bigint not null references public.v20_recommendation_runs(id) on delete restrict,
  publication_key text not null,
  content_hash text not null,
  data_date date not null,
  revision integer not null check (revision > 0),
  published_at timestamptz not null,
  updated_at timestamptz not null default clock_timestamp(),
  unique (run_id),
  foreign key (run_id, publication_key)
    references public.v20_recommendation_runs(id, publication_key) on delete restrict,
  foreign key (run_id, content_hash)
    references public.v20_recommendation_runs(id, content_hash) on delete restrict
);

create table if not exists public.v20_outcome_observations (
  id bigint generated always as identity primary key,
  recommendation_item_id bigint not null
    references public.v20_recommendation_items(id) on delete restrict,
  observed_horizon_days integer not null check (observed_horizon_days in (2, 3, 5, 10, 20, 40, 60)),
  revision integer not null check (revision > 0),
  entry_date date not null,
  entry_price numeric not null check (entry_price > 0),
  exit_date date not null check (exit_date >= entry_date),
  exit_price numeric not null check (exit_price > 0),
  gross_return numeric not null,
  transaction_cost numeric not null check (transaction_cost >= 0),
  net_return numeric not null,
  benchmark_key text not null,
  benchmark_return numeric not null,
  industry_benchmark_key text,
  industry_return numeric,
  excess_return_net numeric not null,
  industry_excess_return_net numeric,
  mfe numeric,
  mae numeric,
  target_hit_first boolean,
  source_version text not null,
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  source_manifest jsonb not null check (pg_catalog.jsonb_typeof(source_manifest) = 'object'),
  calibration_run_key text,
  observation_hash text not null unique check (observation_hash ~ '^[0-9a-f]{64}$'),
  observed_at timestamptz not null,
  recorded_at timestamptz not null default clock_timestamp(),
  unique (recommendation_item_id, observed_horizon_days, revision)
);

create index if not exists v20_model_channel_events_history_idx
  on public.v20_model_channel_events (model_key, channel, changed_at desc, id desc);
create index if not exists v20_model_validation_events_history_idx
  on public.v20_model_validation_events (release_id, recorded_at desc, id desc);
create index if not exists v20_recommendation_runs_history_idx
  on public.v20_recommendation_runs (data_date desc, revision desc, id desc);
create index if not exists v20_recommendation_items_page_idx
  on public.v20_recommendation_items
    (run_id, model_key, horizon_days, public_visible, rank_position)
  include (symbol, group_name, industry, net_opportunity_score, risk_score, confidence)
  where rank_position is not null;
create unique index if not exists v20_recommendation_items_rank_uidx
  on public.v20_recommendation_items (run_id, model_key, horizon_days, rank_position)
  where rank_position is not null;
create index if not exists v20_recommendation_items_symbol_idx
  on public.v20_recommendation_items (symbol, run_id, model_key, horizon_days);
create index if not exists v20_recommendation_items_outcome_queue_idx
  on public.v20_recommendation_items (signal_date, horizon_days, run_id, id)
  include (symbol, model_key, rank_position)
  where public_visible and is_eligible;
create index if not exists v20_recommendation_items_run_horizon_idx
  on public.v20_recommendation_items (run_id, model_key, horizon_days, symbol)
  include (group_name, industry, estimated_total_cost_pct, input_hash)
  where public_visible;
create index if not exists v20_outcome_observations_latest_idx
  on public.v20_outcome_observations
    (recommendation_item_id, observed_horizon_days, revision desc)
  include (net_return, excess_return_net, mfe, mae, observed_at);

alter table public.v20_model_releases enable row level security;
alter table public.v20_model_channel_events enable row level security;
alter table public.v20_model_validation_events enable row level security;
alter table public.v20_model_channel_heads enable row level security;
alter table public.v20_recommendation_runs enable row level security;
alter table public.v20_recommendation_items enable row level security;
alter table public.v20_publication_head enable row level security;
alter table public.v20_outcome_observations enable row level security;

revoke all on table
  public.v20_model_releases,
  public.v20_model_channel_events,
  public.v20_model_validation_events,
  public.v20_model_channel_heads,
  public.v20_recommendation_runs,
  public.v20_recommendation_items,
  public.v20_publication_head,
  public.v20_outcome_observations
from public, anon, authenticated, service_role;

grant select on table
  public.v20_model_releases,
  public.v20_model_channel_events,
  public.v20_model_validation_events,
  public.v20_model_channel_heads,
  public.v20_recommendation_runs,
  public.v20_recommendation_items,
  public.v20_publication_head,
  public.v20_outcome_observations
to service_role;

revoke all on sequence
  public.v20_model_releases_id_seq,
  public.v20_model_channel_events_id_seq,
  public.v20_model_validation_events_id_seq,
  public.v20_recommendation_runs_id_seq,
  public.v20_recommendation_items_id_seq,
  public.v20_outcome_observations_id_seq
from public, anon, authenticated, service_role;

create or replace function public.twss_v20_reject_immutable_change()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  raise exception 'v20_immutable_record' using errcode = '55000';
end;
$$;

do $$
declare
  v_table regclass;
  v_trigger_name text;
begin
  foreach v_table in array array[
    'public.v20_model_channel_events'::regclass,
    'public.v20_model_validation_events'::regclass,
    'public.v20_recommendation_runs'::regclass,
    'public.v20_recommendation_items'::regclass,
    'public.v20_outcome_observations'::regclass
  ]
  loop
    v_trigger_name := 'v20_immutable_' || pg_catalog.replace(v_table::text, 'public.', '');
    execute pg_catalog.format('drop trigger if exists %I on %s', v_trigger_name, v_table);
    execute pg_catalog.format(
      'create trigger %I before update or delete on %s for each row execute function public.twss_v20_reject_immutable_change()',
      v_trigger_name,
      v_table
    );
  end loop;
end
$$;

drop trigger if exists v20_immutable_delete_model_releases on public.v20_model_releases;
create trigger v20_immutable_delete_model_releases
before delete on public.v20_model_releases
for each row execute function public.twss_v20_reject_immutable_change();

revoke all on function public.twss_v20_reject_immutable_change()
  from public, anon, authenticated, service_role;

comment on table public.v20_recommendation_runs is
  'Immutable point-in-time publication metadata, including the exact market context used by that run. signal_count includes all 8 horizons per symbol; research_item_count is the medium-60 subset, so public item count is signal_count - research_item_count.';
comment on column public.v20_recommendation_runs.market_context_snapshot is
  'Full authoritative v20_market_context row locked and copied during publication; included in content_hash so later mutable context updates cannot change this run.';
comment on table public.v20_recommendation_items is
  'Immutable point-in-time recommendation inputs, costs, gates, reasons, risks and ranks.';
comment on table public.v20_outcome_observations is
  'Append-only forward observations; corrections append a new revision and never rewrite history.';
comment on table public.v20_publication_head is
  'The only mutable publication pointer. It is advanced in the same transaction that inserts a validated immutable run.';

create or replace function public.twss_v20_register_model_release(p_release jsonb)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id bigint;
  v_model_key text;
  v_model_version text;
  v_artifact_hash text;
  v_feature_version text;
  v_cost_model_version text;
  v_validation_status text;
begin
  if p_release is null or pg_catalog.jsonb_typeof(p_release) <> 'object' then
    raise exception 'v20_invalid_model_release' using errcode = '22023';
  end if;

  v_model_key := pg_catalog.btrim(coalesce(p_release ->> 'modelKey', ''));
  v_model_version := pg_catalog.btrim(coalesce(p_release ->> 'modelVersion', ''));
  v_artifact_hash := pg_catalog.lower(pg_catalog.btrim(coalesce(p_release ->> 'artifactHash', '')));
  v_feature_version := pg_catalog.btrim(coalesce(p_release ->> 'featureVersion', ''));
  v_cost_model_version := pg_catalog.btrim(coalesce(p_release ->> 'costModelVersion', ''));
  v_validation_status := pg_catalog.btrim(coalesce(p_release ->> 'validationStatus', 'shadow'));

  if v_model_key not in ('short', 'medium')
    or v_model_version = ''
    or v_artifact_hash !~ '^[0-9a-f]{7,128}$'
    or v_feature_version = ''
    or v_cost_model_version = ''
    or v_validation_status not in ('shadow', 'passed', 'failed')
    or pg_catalog.jsonb_typeof(coalesce(p_release -> 'configuration', '{}'::jsonb)) <> 'object'
    or pg_catalog.jsonb_typeof(coalesce(p_release -> 'validationMetrics', '{}'::jsonb)) <> 'object'
  then
    raise exception 'v20_invalid_model_release' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v20-model-release:' || v_model_key || ':' || v_model_version || ':' || v_artifact_hash,
      0
    )
  );

  select r.id
  into v_id
  from public.v20_model_releases r
  where r.model_key = v_model_key
    and r.model_version = v_model_version
    and r.artifact_hash = v_artifact_hash;

  if v_id is not null then
    return v_id;
  end if;

  insert into public.v20_model_releases (
    model_key,
    model_version,
    artifact_hash,
    feature_version,
    cost_model_version,
    calibration_version,
    validation_status,
    configuration,
    validation_metrics,
    registered_by
  )
  values (
    v_model_key,
    v_model_version,
    v_artifact_hash,
    v_feature_version,
    v_cost_model_version,
    nullif(pg_catalog.btrim(coalesce(p_release ->> 'calibrationVersion', '')), ''),
    v_validation_status,
    coalesce(p_release -> 'configuration', '{}'::jsonb),
    coalesce(p_release -> 'validationMetrics', '{}'::jsonb),
    coalesce(nullif(pg_catalog.btrim(coalesce(p_release ->> 'registeredBy', '')), ''), 'service_role')
  )
  returning id into v_id;

  insert into public.v20_model_validation_events (
    release_id,
    validation_status,
    validation_metrics,
    window_start,
    window_end,
    notes,
    recorded_by
  ) values (
    v_id,
    v_validation_status,
    coalesce(p_release -> 'validationMetrics', '{}'::jsonb),
    (p_release ->> 'validationWindowStart')::date,
    (p_release ->> 'validationWindowEnd')::date,
    nullif(pg_catalog.left(pg_catalog.btrim(coalesce(p_release ->> 'validationNotes', '')), 2000), ''),
    coalesce(nullif(pg_catalog.btrim(coalesce(p_release ->> 'registeredBy', '')), ''), 'service_role')
  );

  return v_id;
end;
$$;

create or replace function public.twss_v20_record_model_validation(p_validation jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_release_id bigint := (p_validation ->> 'releaseId')::bigint;
  v_status text := pg_catalog.btrim(coalesce(p_validation ->> 'validationStatus', ''));
  v_metrics jsonb := coalesce(p_validation -> 'validationMetrics', '{}'::jsonb);
  v_event_id bigint;
begin
  if p_validation is null
    or pg_catalog.jsonb_typeof(p_validation) <> 'object'
    or v_release_id is null
    or v_status not in ('shadow', 'passed', 'failed')
    or pg_catalog.jsonb_typeof(v_metrics) <> 'object'
    or not exists (select 1 from public.v20_model_releases r where r.id = v_release_id)
  then
    raise exception 'v20_invalid_model_validation' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-model-validation:' || v_release_id::text, 0)
  );

  insert into public.v20_model_validation_events (
    release_id,
    validation_status,
    validation_metrics,
    window_start,
    window_end,
    notes,
    recorded_by
  ) values (
    v_release_id,
    v_status,
    v_metrics,
    (p_validation ->> 'windowStart')::date,
    (p_validation ->> 'windowEnd')::date,
    nullif(pg_catalog.left(pg_catalog.btrim(coalesce(p_validation ->> 'notes', '')), 2000), ''),
    coalesce(nullif(pg_catalog.btrim(coalesce(p_validation ->> 'recordedBy', '')), ''), 'service_role')
  )
  returning id into v_event_id;

  update public.v20_model_releases
  set validation_status = v_status,
      validation_metrics = v_metrics
  where id = v_release_id;

  return pg_catalog.jsonb_build_object(
    'releaseId', v_release_id,
    'validationEventId', v_event_id,
    'validationStatus', v_status,
    'validationMetrics', v_metrics
  );
end;
$$;

create or replace function public.twss_v20_set_model_channel(p_change jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_model_key text;
  v_channel text;
  v_release_id bigint;
  v_previous_release_id bigint;
  v_event_id bigint;
  v_release public.v20_model_releases%rowtype;
begin
  if p_change is null or pg_catalog.jsonb_typeof(p_change) <> 'object' then
    raise exception 'v20_invalid_channel_change' using errcode = '22023';
  end if;

  v_model_key := pg_catalog.btrim(coalesce(p_change ->> 'modelKey', ''));
  v_channel := pg_catalog.btrim(coalesce(p_change ->> 'channel', ''));
  v_release_id := (p_change ->> 'releaseId')::bigint;

  if v_model_key not in ('short', 'medium')
    or v_channel not in ('champion', 'challenger')
    or nullif(pg_catalog.btrim(coalesce(p_change ->> 'reason', '')), '') is null
  then
    raise exception 'v20_invalid_channel_change' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-model-channel:' || v_model_key, 0)
  );

  select * into v_release
  from public.v20_model_releases r
  where r.id = v_release_id;

  if not found or v_release.model_key <> v_model_key then
    raise exception 'v20_model_release_not_found' using errcode = '22023';
  end if;
  if v_channel = 'champion' and v_release.validation_status <> 'passed' then
    raise exception 'v20_champion_requires_passed_validation' using errcode = '22023';
  end if;
  if exists (
    select 1 from public.v20_model_channel_heads h
    where h.model_key = v_model_key
      and h.channel <> v_channel
      and h.release_id = v_release_id
  ) then
    raise exception 'v20_release_cannot_fill_both_channels' using errcode = '22023';
  end if;

  select h.release_id into v_previous_release_id
  from public.v20_model_channel_heads h
  where h.model_key = v_model_key and h.channel = v_channel;

  if v_previous_release_id = v_release_id then
    return pg_catalog.jsonb_build_object(
      'modelKey', v_model_key,
      'channel', v_channel,
      'releaseId', v_release_id,
      'changed', false
    );
  end if;

  insert into public.v20_model_channel_events (
    model_key, channel, release_id, previous_release_id, reason, changed_by
  ) values (
    v_model_key,
    v_channel,
    v_release_id,
    v_previous_release_id,
    pg_catalog.left(pg_catalog.btrim(p_change ->> 'reason'), 1000),
    coalesce(nullif(pg_catalog.btrim(coalesce(p_change ->> 'changedBy', '')), ''), 'service_role')
  )
  returning id into v_event_id;

  insert into public.v20_model_channel_heads (
    model_key, channel, release_id, event_id, changed_at
  ) values (
    v_model_key, v_channel, v_release_id, v_event_id, clock_timestamp()
  )
  on conflict (model_key, channel) do update
  set release_id = excluded.release_id,
      event_id = excluded.event_id,
      changed_at = excluded.changed_at;

  return pg_catalog.jsonb_build_object(
    'modelKey', v_model_key,
    'channel', v_channel,
    'releaseId', v_release_id,
    'previousReleaseId', v_previous_release_id,
    'eventId', v_event_id,
    'changed', true
  );
end;
$$;

create or replace function public.twss_v20_read_model_channels()
returns table (
  model_key text,
  channel text,
  release_id bigint,
  model_version text,
  artifact_hash text,
  feature_version text,
  cost_model_version text,
  calibration_version text,
  validation_status text,
  validation_metrics jsonb,
  changed_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    h.model_key,
    h.channel,
    h.release_id,
    r.model_version,
    r.artifact_hash,
    r.feature_version,
    r.cost_model_version,
    r.calibration_version,
    r.validation_status,
    r.validation_metrics,
    h.changed_at
  from public.v20_model_channel_heads h
  join public.v20_model_releases r on r.id = h.release_id
  order by h.model_key, h.channel;
$$;

create or replace function public.twss_v20_promote_challenger(p_change jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_model_key text := pg_catalog.btrim(coalesce(p_change ->> 'modelKey', ''));
  v_reason text := nullif(pg_catalog.btrim(coalesce(p_change ->> 'reason', '')), '');
  v_changed_by text := coalesce(
    nullif(pg_catalog.btrim(coalesce(p_change ->> 'changedBy', '')), ''),
    'service_role'
  );
  v_old_champion_id bigint;
  v_new_champion_id bigint;
  v_champion_event_id bigint;
  v_challenger_event_id bigint;
begin
  if p_change is null
    or pg_catalog.jsonb_typeof(p_change) <> 'object'
    or v_model_key not in ('short', 'medium')
    or v_reason is null
  then
    raise exception 'v20_invalid_challenger_promotion' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-model-channel:' || v_model_key, 0)
  );

  select
    max(h.release_id) filter (where h.channel = 'champion'),
    max(h.release_id) filter (where h.channel = 'challenger')
  into v_old_champion_id, v_new_champion_id
  from public.v20_model_channel_heads h
  where h.model_key = v_model_key;

  if v_new_champion_id is null then
    raise exception 'v20_challenger_not_configured' using errcode = '22023';
  end if;
  if not exists (
    select 1
    from public.v20_model_releases r
    where r.id = v_new_champion_id
      and r.model_key = v_model_key
      and r.validation_status = 'passed'
  ) then
    raise exception 'v20_champion_requires_passed_validation' using errcode = '22023';
  end if;

  insert into public.v20_model_channel_events (
    model_key, channel, release_id, previous_release_id, reason, changed_by
  ) values (
    v_model_key,
    'champion',
    v_new_champion_id,
    v_old_champion_id,
    pg_catalog.left(v_reason, 1000),
    v_changed_by
  )
  returning id into v_champion_event_id;

  if v_old_champion_id is not null then
    insert into public.v20_model_channel_events (
      model_key, channel, release_id, previous_release_id, reason, changed_by
    ) values (
      v_model_key,
      'challenger',
      v_old_champion_id,
      v_new_champion_id,
      pg_catalog.left('automatic rollback candidate after promotion: ' || v_reason, 1000),
      v_changed_by
    )
    returning id into v_challenger_event_id;
  end if;

  delete from public.v20_model_channel_heads h
  where h.model_key = v_model_key;

  insert into public.v20_model_channel_heads (
    model_key, channel, release_id, event_id, changed_at
  ) values (
    v_model_key, 'champion', v_new_champion_id, v_champion_event_id, clock_timestamp()
  );

  if v_old_champion_id is not null then
    insert into public.v20_model_channel_heads (
      model_key, channel, release_id, event_id, changed_at
    ) values (
      v_model_key, 'challenger', v_old_champion_id, v_challenger_event_id, clock_timestamp()
    );
  end if;

  return pg_catalog.jsonb_build_object(
    'modelKey', v_model_key,
    'championReleaseId', v_new_champion_id,
    'challengerReleaseId', v_old_champion_id,
    'championEventId', v_champion_event_id,
    'challengerEventId', v_challenger_event_id,
    'promoted', true
  );
end;
$$;

revoke all on function public.twss_v20_register_model_release(jsonb)
  from public, anon, authenticated;
revoke all on function public.twss_v20_record_model_validation(jsonb)
  from public, anon, authenticated;
revoke all on function public.twss_v20_set_model_channel(jsonb)
  from public, anon, authenticated;
revoke all on function public.twss_v20_read_model_channels()
  from public, anon, authenticated;
revoke all on function public.twss_v20_promote_challenger(jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v20_register_model_release(jsonb) to service_role;
grant execute on function public.twss_v20_record_model_validation(jsonb) to service_role;
grant execute on function public.twss_v20_set_model_channel(jsonb) to service_role;
grant execute on function public.twss_v20_read_model_channels() to service_role;
grant execute on function public.twss_v20_promote_challenger(jsonb) to service_role;

create or replace function public.twss_v20_signal_data_cutoff(
  p_query jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_data_date date;
  v_model_version text;
  v_signal_count integer;
  v_data_cutoff_at timestamptz;
begin
  if p_query is null or pg_catalog.jsonb_typeof(p_query) <> 'object' then
    raise exception 'v20_invalid_signal_cutoff_query' using errcode = '22023';
  end if;

  v_data_date := (p_query ->> 'dataDate')::date;
  v_model_version := pg_catalog.btrim(coalesce(p_query ->> 'modelVersion', '20.1'));

  if v_data_date is null
    or v_model_version = ''
    or pg_catalog.length(v_model_version) > 128
  then
    raise exception 'v20_invalid_signal_cutoff_query' using errcode = '22023';
  end if;

  select
    count(*)::integer,
    max(greatest(s.generated_at, s.updated_at))
  into v_signal_count, v_data_cutoff_at
  from public.v20_model_signals s
  where s.signal_date = v_data_date
    and s.model_version = v_model_version;

  if v_signal_count = 0 or v_data_cutoff_at is null then
    raise exception 'v20_signal_data_cutoff_unavailable' using errcode = '22023';
  end if;

  return pg_catalog.jsonb_build_object(
    'dataDate', v_data_date,
    'modelVersion', v_model_version,
    'signalCount', v_signal_count,
    'dataCutoffAt', v_data_cutoff_at
  );
end;
$$;

revoke all on function public.twss_v20_signal_data_cutoff(jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.twss_v20_signal_data_cutoff(jsonb)
  to service_role;

comment on function public.twss_v20_signal_data_cutoff(jsonb) is
  'Service-only staging cutoff resolver. Uses the newest generated_at or updated_at and rejects an empty signal cycle.';

create or replace function public.twss_v20_publish_recommendation_run(p_request jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_data_date date;
  v_data_cutoff_at timestamptz;
  v_model_version text;
  v_feature_version text;
  v_cost_model_version text;
  v_calibration_version text;
  v_code_hash text;
  v_source_version text;
  v_source_hash text;
  v_source_manifest jsonb;
  v_model_manifest jsonb;
  v_market_context_snapshot jsonb;
  v_authoritative_market_context public.v20_market_context%rowtype;
  v_market_regime text;
  v_expected_symbol_count integer;
  v_scored_symbol_count integer;
  v_cycle_completeness numeric;
  v_deadletter_count integer;
  v_terminal_errors jsonb;
  v_published_by text;
  v_universe_count integer;
  v_actual_symbol_count integer;
  v_signal_count integer;
  v_incomplete_symbols integer;
  v_invalid_rows integer;
  v_queue_terminal_count integer;
  v_queue_unsettled_count integer;
  v_eligible_count integer;
  v_research_count integer;
  v_cutoff_signal_count integer;
  v_authoritative_data_cutoff_at timestamptz;
  v_calibration_mismatch_count integer;
  v_previous_run_id bigint;
  v_previous_data_date date;
  v_previous_data_cutoff_at timestamptz;
  v_existing_run_id bigint;
  v_revision integer;
  v_content_hash text;
  v_run_id bigint;
  v_inserted_items integer;
  v_published_at timestamptz := clock_timestamp();
begin
  if p_request is null or pg_catalog.jsonb_typeof(p_request) <> 'object' then
    raise exception 'v20_invalid_publication_request' using errcode = '22023';
  end if;

  v_data_date := (p_request ->> 'dataDate')::date;
  v_data_cutoff_at := (p_request ->> 'dataCutoffAt')::timestamptz;
  v_model_version := pg_catalog.btrim(coalesce(p_request ->> 'modelVersion', ''));
  v_feature_version := pg_catalog.btrim(coalesce(p_request ->> 'featureVersion', ''));
  v_cost_model_version := pg_catalog.btrim(coalesce(p_request ->> 'costModelVersion', ''));
  v_calibration_version := nullif(pg_catalog.btrim(coalesce(p_request ->> 'calibrationVersion', '')), '');
  v_code_hash := pg_catalog.btrim(coalesce(p_request ->> 'codeHash', ''));
  v_source_version := pg_catalog.btrim(coalesce(p_request ->> 'sourceVersion', ''));
  v_source_hash := pg_catalog.lower(pg_catalog.btrim(coalesce(p_request ->> 'sourceHash', '')));
  v_source_manifest := coalesce(p_request -> 'sourceManifest', '{}'::jsonb);
  v_model_manifest := coalesce(p_request -> 'modelManifest', '{}'::jsonb);
  v_market_context_snapshot := coalesce(p_request -> 'marketContext', '{}'::jsonb);
  v_market_regime := nullif(pg_catalog.btrim(coalesce(p_request ->> 'marketRegime', '')), '');
  v_expected_symbol_count := (p_request ->> 'expectedSymbolCount')::integer;
  v_scored_symbol_count := (p_request ->> 'scoredSymbolCount')::integer;
  v_cycle_completeness := (p_request ->> 'cycleCompleteness')::numeric;
  v_deadletter_count := coalesce((p_request ->> 'deadletterCount')::integer, 0);
  v_terminal_errors := coalesce(p_request -> 'terminalErrors', '[]'::jsonb);
  v_published_by := coalesce(
    nullif(pg_catalog.btrim(coalesce(p_request ->> 'publishedBy', '')), ''),
    'service_role'
  );

  if v_data_date is null
    or v_data_cutoff_at is null
    or v_data_cutoff_at > clock_timestamp() + interval '5 minutes'
    or v_model_version = ''
    or v_feature_version = ''
    or v_cost_model_version = ''
    or v_code_hash !~ '^[0-9a-f]{64}$'
    or v_source_version = ''
    or v_source_hash !~ '^[0-9a-f]{64}$'
    or pg_catalog.jsonb_typeof(v_source_manifest) <> 'object'
    or v_source_manifest = '{}'::jsonb
    or pg_catalog.jsonb_typeof(v_source_manifest -> 'sources') <> 'object'
    or coalesce(v_source_manifest -> 'sources', '{}'::jsonb) = '{}'::jsonb
    or pg_catalog.jsonb_typeof(v_model_manifest) <> 'object'
    or not (v_model_manifest ? 'short' and v_model_manifest ? 'medium')
    or pg_catalog.jsonb_typeof(v_market_context_snapshot) <> 'object'
    or v_market_context_snapshot = '{}'::jsonb
    or not (
      v_market_context_snapshot ?& array[
        'data_date', 'model_version', 'regime', 'regime_score', 'confidence',
        'completeness', 'status', 'taiex', 'tpex', 'tx_futures', 'breadth',
        'institutional', 'global_context', 'source_dates', 'degraded_sources',
        'fetched_at', 'generated_at', 'updated_at'
      ]
    )
    or v_market_context_snapshot ->> 'data_date' <> v_data_date::text
    or v_market_context_snapshot ->> 'model_version' <> v_model_version
    or v_market_regime is null
    or v_market_context_snapshot ->> 'regime' <> v_market_regime
    or v_source_manifest #>> '{sources,marketContext,available}' <> 'true'
    or v_source_manifest #>> '{sources,marketContext,dataDate}' <> v_data_date::text
    or v_expected_symbol_count is null
    or v_expected_symbol_count <= 0
    or v_scored_symbol_count <> v_expected_symbol_count
    or v_cycle_completeness <> 100
    or v_deadletter_count <> 0
    or pg_catalog.jsonb_typeof(v_terminal_errors) <> 'array'
    or pg_catalog.jsonb_array_length(v_terminal_errors) <> 0
  then
    raise exception 'v20_unpublishable_cycle_metadata' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v20-immutable-publication:public',
      0
    )
  );

  -- The worker resolves a cutoff before constructing source manifests.  A
  -- SHARE table lock closes the gap between that read and this transaction:
  -- concurrent staging inserts/updates wait, while any change that won the
  -- race before this lock is detected by the exact timestamp comparison.
  lock table public.v20_model_signals in share mode;

  select
    count(*)::integer,
    max(greatest(s.generated_at, s.updated_at))
  into v_cutoff_signal_count, v_authoritative_data_cutoff_at
  from public.v20_model_signals s
  where s.signal_date = v_data_date
    and s.model_version = v_model_version;

  if v_cutoff_signal_count = 0 or v_authoritative_data_cutoff_at is null then
    raise exception 'v20_signal_data_cutoff_unavailable' using errcode = '22023';
  end if;

  if v_data_cutoff_at is distinct from v_authoritative_data_cutoff_at then
    raise exception 'v20_signal_data_cutoff_changed expected %, found %',
      v_data_cutoff_at, v_authoritative_data_cutoff_at using errcode = '40001';
  end if;

  select c.*
  into v_authoritative_market_context
  from public.v20_market_context c
  where c.data_date = v_data_date
    and c.model_version = v_model_version
  for share of c;

  if not found then
    raise exception 'v20_market_context_not_found' using errcode = '22023';
  end if;

  if v_market_context_snapshot <> pg_catalog.to_jsonb(v_authoritative_market_context) then
    raise exception 'v20_market_context_mismatch' using errcode = '22023';
  end if;

  select h.run_id, r.data_date, r.data_cutoff_at
  into v_previous_run_id, v_previous_data_date, v_previous_data_cutoff_at
  from public.v20_publication_head h
  join public.v20_recommendation_runs r on r.id = h.run_id
  where h.audience = 'public'
  for update of h;

  if v_previous_data_date is not null and v_data_date < v_previous_data_date then
    raise exception 'v20_publication_date_regression' using errcode = '22023';
  end if;
  if v_previous_data_date = v_data_date
    and v_previous_data_cutoff_at is not null
    and v_data_cutoff_at < v_previous_data_cutoff_at
  then
    raise exception 'v20_publication_cutoff_regression' using errcode = '22023';
  end if;

  select count(*)::integer
  into v_universe_count
  from public.v20_universe_membership u
  where u.as_of_date = v_data_date
    and u.model_version = v_model_version
    and u.active;

  if v_universe_count <> v_expected_symbol_count then
    raise exception 'v20_incomplete_universe expected %, found %',
      v_expected_symbol_count, v_universe_count using errcode = '22023';
  end if;

  select count(*)::integer, count(distinct s.symbol)::integer
  into v_signal_count, v_actual_symbol_count
  from public.v20_model_signals s
  join public.v20_universe_membership u
    on u.symbol = s.symbol
    and u.as_of_date = s.signal_date
    and u.model_version = s.model_version
    and u.active
  where s.signal_date = v_data_date
    and s.model_version = v_model_version;

  if v_actual_symbol_count <> v_scored_symbol_count
    or v_signal_count <> v_expected_symbol_count * 8
  then
    raise exception 'v20_incomplete_signal_cycle expected % symbols/% rows, found %/%',
      v_expected_symbol_count,
      v_expected_symbol_count * 8,
      v_actual_symbol_count,
      v_signal_count
      using errcode = '22023';
  end if;

  select count(*)::integer
  into v_incomplete_symbols
  from (
    select u.symbol
    from public.v20_universe_membership u
    left join public.v20_model_signals s
      on s.symbol = u.symbol
      and s.signal_date = u.as_of_date
      and s.model_version = u.model_version
    where u.as_of_date = v_data_date
      and u.model_version = v_model_version
      and u.active
    group by u.symbol
    having count(*) filter (
      where s.model_key = 'short' and s.horizon_days in (2, 3, 5, 10)
    ) <> 4
    or count(*) filter (
      where s.model_key = 'medium' and s.horizon_days in (10, 20, 40, 60)
    ) <> 4
  ) incomplete;

  if v_incomplete_symbols <> 0 then
    raise exception 'v20_missing_required_horizons for % symbols', v_incomplete_symbols
      using errcode = '22023';
  end if;

  select count(*)::integer
  into v_invalid_rows
  from public.v20_model_signals s
  join public.v20_universe_membership u
    on u.symbol = s.symbol
    and u.as_of_date = s.signal_date
    and u.model_version = s.model_version
    and u.active
  where s.signal_date = v_data_date
    and s.model_version = v_model_version
    and (
      s.raw_opportunity_score is null
      or s.net_opportunity_score is null
      or s.estimated_commission_pct is null
      or s.estimated_tax_pct is null
      or s.estimated_slippage_pct is null
      or s.estimated_spread_pct is null
      or s.estimated_total_cost_pct is null
      or s.downside_penalty_score is null
      or s.turnover_penalty_score is null
      or s.cost_penalty_score is null
      or s.turnover_exposure is null
      or nullif(pg_catalog.btrim(coalesce(s.liquidity_grade, '')), '') is null
      or s.recommended_holding_days is null
      or pg_catalog.abs(s.opportunity_score - s.net_opportunity_score) > 0.0001
      or pg_catalog.abs(
        s.estimated_total_cost_pct
        - (
          s.estimated_commission_pct
          + s.estimated_tax_pct
          + s.estimated_slippage_pct
          + s.estimated_spread_pct
        )
      ) > 0.0001
      or s.research_only is distinct from (s.model_key = 'medium' and s.horizon_days = 60)
      or pg_catalog.jsonb_typeof(s.feature_scores) <> 'object'
      or pg_catalog.jsonb_typeof(s.gate_results) <> 'object'
      or pg_catalog.jsonb_typeof(s.reasons) <> 'array'
      or pg_catalog.jsonb_typeof(s.risks) <> 'array'
      or pg_catalog.jsonb_typeof(s.invalidation_conditions) <> 'array'
      or pg_catalog.jsonb_typeof(s.source_dates) <> 'object'
    );

  if v_invalid_rows <> 0 then
    raise exception 'v20_invalid_v21_signal_contract for % rows', v_invalid_rows
      using errcode = '22023';
  end if;

  select count(*)::integer
  into v_calibration_mismatch_count
  from public.v20_model_signals s
  join public.v20_universe_membership u
    on u.symbol = s.symbol
    and u.as_of_date = s.signal_date
    and u.model_version = s.model_version
    and u.active
  where s.signal_date = v_data_date
    and s.model_version = v_model_version
    and s.calibration_version is distinct from v_calibration_version;

  if v_calibration_mismatch_count <> 0 then
    raise exception 'v20_calibration_version_mismatch for % rows', v_calibration_mismatch_count
      using errcode = '22023';
  end if;

  select count(*)::integer
  into v_queue_terminal_count
  from public.v20_model_dirty_queue q
  where q.data_date = v_data_date
    and q.model_version = v_model_version
    and q.status = 'error'
    and q.attempt_count >= q.max_attempts;

  if v_queue_terminal_count <> 0 then
    raise exception 'v20_terminal_dirty_queue_errors %', v_queue_terminal_count
      using errcode = '22023';
  end if;

  select count(*)::integer
  into v_queue_unsettled_count
  from public.v20_model_dirty_queue q
  where q.data_date = v_data_date
    and q.model_version = v_model_version
    and (
      q.status in ('pending', 'error')
      or (
        q.status = 'running'
        and q.dirty_version > coalesce(q.claimed_version, 0)
      )
    );

  if v_queue_unsettled_count <> 0 then
    raise exception 'v20_dirty_queue_not_settled %', v_queue_unsettled_count
      using errcode = '22023';
  end if;

  select
    count(*) filter (where s.official and s.gate_passed)::integer,
    count(*) filter (where s.research_only)::integer
  into v_eligible_count, v_research_count
  from public.v20_model_signals s
  join public.v20_universe_membership u
    on u.symbol = s.symbol
    and u.as_of_date = s.signal_date
    and u.model_version = s.model_version
    and u.active
  where s.signal_date = v_data_date
    and s.model_version = v_model_version;

  select pg_catalog.encode(
    extensions.digest(
      pg_catalog.jsonb_build_object(
        'dataDate', v_data_date,
        'dataCutoffAt', v_data_cutoff_at,
        'modelVersion', v_model_version,
        'featureVersion', v_feature_version,
        'costModelVersion', v_cost_model_version,
        'calibrationVersion', v_calibration_version,
        'codeHash', v_code_hash,
        'sourceVersion', v_source_version,
        'sourceHash', v_source_hash,
        'sourceManifest', v_source_manifest,
        'modelManifest', v_model_manifest,
        'marketContext', v_market_context_snapshot,
        'marketRegime', v_market_regime,
        'expectedSymbolCount', v_expected_symbol_count
      )::text
      || ':'
      || pg_catalog.string_agg(
        pg_catalog.encode(
          extensions.digest(
            (pg_catalog.to_jsonb(s) - 'generated_at' - 'updated_at')::text,
            'sha256'
          ),
          'hex'
        ),
        '|' order by s.symbol, s.model_key, s.horizon_days
      ),
      'sha256'
    ),
    'hex'
  )
  into v_content_hash
  from public.v20_model_signals s
  join public.v20_universe_membership u
    on u.symbol = s.symbol
    and u.as_of_date = s.signal_date
    and u.model_version = s.model_version
    and u.active
  where s.signal_date = v_data_date
    and s.model_version = v_model_version;

  select r.id
  into v_existing_run_id
  from public.v20_recommendation_runs r
  where r.content_hash = v_content_hash;

  if v_existing_run_id is not null then
    return pg_catalog.jsonb_build_object(
      'runId', v_existing_run_id,
      'publicationKey', v_content_hash,
      'contentHash', v_content_hash,
      'dataDate', v_data_date,
      'idempotent', true,
      'headChanged', false
    );
  end if;

  select coalesce(max(r.revision), 0) + 1
  into v_revision
  from public.v20_recommendation_runs r
  where r.data_date = v_data_date
    and r.model_version = v_model_version;

  insert into public.v20_recommendation_runs (
    publication_key,
    data_date,
    data_cutoff_at,
    revision,
    model_version,
    feature_version,
    cost_model_version,
    calibration_version,
    code_hash,
    source_version,
    source_hash,
    source_manifest,
    model_manifest,
    market_context_snapshot,
    market_regime,
    expected_symbol_count,
    scored_symbol_count,
    signal_count,
    eligible_item_count,
    research_item_count,
    cycle_completeness,
    deadletter_count,
    terminal_errors,
    content_hash,
    published_by,
    published_at
  ) values (
    v_content_hash,
    v_data_date,
    v_data_cutoff_at,
    v_revision,
    v_model_version,
    v_feature_version,
    v_cost_model_version,
    v_calibration_version,
    v_code_hash,
    v_source_version,
    v_source_hash,
    v_source_manifest,
    v_model_manifest,
    v_market_context_snapshot,
    v_market_regime,
    v_expected_symbol_count,
    v_scored_symbol_count,
    v_signal_count,
    v_eligible_count,
    v_research_count,
    v_cycle_completeness,
    v_deadletter_count,
    v_terminal_errors,
    v_content_hash,
    v_published_by,
    v_published_at
  )
  returning id into v_run_id;

  with staged as (
    select
      s.*,
      (s.official and s.gate_passed) as is_eligible,
      pg_catalog.encode(
        extensions.digest(
          (pg_catalog.to_jsonb(s) - 'generated_at' - 'updated_at')::text,
          'sha256'
        ),
        'hex'
      ) as input_hash
    from public.v20_model_signals s
    join public.v20_universe_membership u
      on u.symbol = s.symbol
      and u.as_of_date = s.signal_date
      and u.model_version = s.model_version
      and u.active
    where s.signal_date = v_data_date
      and s.model_version = v_model_version
  ), eligible_ranks as (
    select
      s.symbol,
      s.model_key,
      s.horizon_days,
      pg_catalog.row_number() over (
        partition by s.model_key, s.horizon_days
        order by
          s.net_opportunity_score desc,
          s.risk_score asc,
          s.confidence desc,
          s.symbol
      )::integer as rank_position,
      pg_catalog.round(
        100 * (
          1 - pg_catalog.percent_rank() over (
            partition by s.model_key, s.horizon_days
            order by
              s.net_opportunity_score desc,
              s.risk_score asc,
              s.confidence desc,
              s.symbol
          )
        )::numeric,
        2
      ) as market_percentile
    from staged s
    where s.is_eligible
  )
  insert into public.v20_recommendation_items (
    run_id,
    symbol,
    signal_date,
    model_key,
    horizon_days,
    model_version,
    group_name,
    name,
    market,
    industry,
    instrument_type,
    strategy_key,
    is_eligible,
    public_visible,
    research_only,
    rank_position,
    previous_rank,
    rank_delta,
    market_percentile,
    raw_opportunity_score,
    net_opportunity_score,
    risk_score,
    confidence,
    completeness,
    estimated_commission_pct,
    estimated_tax_pct,
    estimated_slippage_pct,
    estimated_spread_pct,
    estimated_total_cost_pct,
    downside_penalty_score,
    turnover_penalty_score,
    cost_penalty_score,
    turnover_exposure,
    liquidity_grade,
    opportunity_state,
    prediction_basis,
    calibrated_up_probability,
    expected_return_net,
    expected_excess_return_gross,
    expected_excess_return_net,
    calibration_sample_count,
    benchmark_key,
    recommended_holding_days,
    recommended_action,
    entry_low,
    entry_high,
    breakout_price,
    no_chase_price,
    stop_loss,
    take_profit_1,
    take_profit_2,
    risk_reward_ratio,
    feature_scores,
    gate_results,
    reasons,
    risks,
    invalidation_conditions,
    source_manifest,
    input_hash,
    recorded_at
  )
  select
    v_run_id,
    s.symbol,
    s.signal_date,
    s.model_key,
    s.horizon_days,
    s.model_version,
    s.group_name,
    s.name,
    s.market,
    s.industry,
    s.instrument_type,
    s.strategy_key,
    s.is_eligible,
    not s.research_only,
    s.research_only,
    er.rank_position,
    prior.rank_position,
    case
      when prior.rank_position is null or er.rank_position is null then null
      else prior.rank_position - er.rank_position
    end,
    er.market_percentile,
    s.raw_opportunity_score,
    s.net_opportunity_score,
    s.risk_score,
    s.confidence,
    s.completeness,
    s.estimated_commission_pct,
    s.estimated_tax_pct,
    s.estimated_slippage_pct,
    s.estimated_spread_pct,
    s.estimated_total_cost_pct,
    s.downside_penalty_score,
    s.turnover_penalty_score,
    s.cost_penalty_score,
    s.turnover_exposure,
    s.liquidity_grade,
    case
      when not s.is_eligible then 'excluded'
      when s.recommended_action in ('wait', 'waiting') then 'waiting'
      when s.recommended_action in ('weakening', 'reduce') then 'weakening'
      else 'qualified'
    end,
    s.prediction_basis,
    case
      when s.calibration_sample_count >= 100
        and s.prediction_basis ilike '%calibrat%'
      then s.up_probability
      else null
    end,
    s.expected_return_net,
    case
      when s.calibration_sample_count >= 100
        and s.prediction_basis ilike '%calibrat%'
      then s.expected_excess_return_gross
      else null
    end,
    case
      when s.calibration_sample_count >= 100
        and s.prediction_basis ilike '%calibrat%'
      then s.expected_excess_return_net
      else null
    end,
    s.calibration_sample_count,
    s.benchmark_key,
    s.recommended_holding_days,
    s.recommended_action,
    s.entry_low,
    s.entry_high,
    s.breakout_price,
    s.no_chase_price,
    s.stop_loss,
    s.take_profit_1,
    s.take_profit_2,
    s.risk_reward_ratio,
    s.feature_scores,
    s.gate_results,
    s.reasons,
    s.risks,
    s.invalidation_conditions,
    pg_catalog.jsonb_build_object(
      'sourceVersion', v_source_version,
      'sourceHash', v_source_hash,
      'calibrationVersion', s.calibration_version,
      'sourceDates', s.source_dates,
      'signalGeneratedAt', s.generated_at,
      'signalUpdatedAt', s.updated_at
    ),
    s.input_hash,
    v_published_at
  from staged s
  left join eligible_ranks er
    on er.symbol = s.symbol
    and er.model_key = s.model_key
    and er.horizon_days = s.horizon_days
  left join public.v20_recommendation_items prior
    on prior.run_id = v_previous_run_id
    and prior.symbol = s.symbol
    and prior.model_key = s.model_key
    and prior.horizon_days = s.horizon_days;

  get diagnostics v_inserted_items = row_count;
  if v_inserted_items <> v_signal_count then
    raise exception 'v20_atomic_item_copy_mismatch expected %, inserted %',
      v_signal_count, v_inserted_items using errcode = '22023';
  end if;

  insert into public.v20_publication_head (
    audience,
    run_id,
    publication_key,
    content_hash,
    data_date,
    revision,
    published_at,
    updated_at
  ) values (
    'public',
    v_run_id,
    v_content_hash,
    v_content_hash,
    v_data_date,
    v_revision,
    v_published_at,
    v_published_at
  )
  on conflict (audience) do update
  set run_id = excluded.run_id,
      publication_key = excluded.publication_key,
      content_hash = excluded.content_hash,
      data_date = excluded.data_date,
      revision = excluded.revision,
      published_at = excluded.published_at,
      updated_at = excluded.updated_at;

  return pg_catalog.jsonb_build_object(
    'runId', v_run_id,
    'publicationKey', v_content_hash,
    'contentHash', v_content_hash,
    'dataDate', v_data_date,
    'revision', v_revision,
    'items', v_inserted_items,
    'publicItems', v_inserted_items - v_research_count,
    'eligibleItems', v_eligible_count,
    'researchItems', v_research_count,
    'publishedAt', v_published_at,
    'idempotent', false,
    'headChanged', true
  );
end;
$$;

revoke all on function public.twss_v20_publish_recommendation_run(jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v20_publish_recommendation_run(jsonb)
  to service_role;

comment on function public.twss_v20_publish_recommendation_run(jsonb) is
  'Service-only atomic publisher. It requires a complete eight-horizon universe, v20.1 costs/features/hashes, zero dead letters and zero terminal errors.';

create or replace function public.twss_v20_append_outcome_observation(p_observation jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_item public.v20_recommendation_items%rowtype;
  v_item_id bigint;
  v_horizon_days integer;
  v_entry_date date;
  v_entry_price numeric;
  v_exit_date date;
  v_exit_price numeric;
  v_transaction_cost numeric;
  v_benchmark_key text;
  v_benchmark_return numeric;
  v_industry_benchmark_key text;
  v_industry_return numeric;
  v_source_version text;
  v_source_hash text;
  v_source_manifest jsonb;
  v_observed_at timestamptz;
  v_gross_return numeric;
  v_net_return numeric;
  v_excess_return numeric;
  v_industry_excess_return numeric;
  v_revision integer;
  v_observation_hash text;
  v_existing_id bigint;
  v_id bigint;
begin
  if p_observation is null or pg_catalog.jsonb_typeof(p_observation) <> 'object' then
    raise exception 'v20_invalid_outcome_observation' using errcode = '22023';
  end if;

  v_item_id := (p_observation ->> 'recommendationItemId')::bigint;
  v_horizon_days := (p_observation ->> 'horizonDays')::integer;
  v_entry_date := (p_observation ->> 'entryDate')::date;
  v_entry_price := (p_observation ->> 'entryPrice')::numeric;
  v_exit_date := (p_observation ->> 'exitDate')::date;
  v_exit_price := (p_observation ->> 'exitPrice')::numeric;
  v_transaction_cost := (p_observation ->> 'transactionCost')::numeric;
  v_benchmark_key := pg_catalog.btrim(coalesce(p_observation ->> 'benchmarkKey', ''));
  v_benchmark_return := (p_observation ->> 'benchmarkReturn')::numeric;
  v_industry_benchmark_key := nullif(
    pg_catalog.btrim(coalesce(p_observation ->> 'industryBenchmarkKey', '')),
    ''
  );
  v_industry_return := (p_observation ->> 'industryReturn')::numeric;
  v_source_version := pg_catalog.btrim(coalesce(p_observation ->> 'sourceVersion', ''));
  v_source_hash := pg_catalog.lower(pg_catalog.btrim(coalesce(p_observation ->> 'sourceHash', '')));
  v_source_manifest := coalesce(p_observation -> 'sourceManifest', '{}'::jsonb);
  v_observed_at := coalesce(
    (p_observation ->> 'observedAt')::timestamptz,
    clock_timestamp()
  );

  if v_item_id is null
    or v_horizon_days not in (2, 3, 5, 10, 20, 40, 60)
    or v_entry_date is null
    or v_entry_price is null
    or v_entry_price <= 0
    or v_exit_date is null
    or v_exit_date < v_entry_date
    or v_exit_price is null
    or v_exit_price <= 0
    or v_transaction_cost is null
    or v_transaction_cost < 0
    or v_benchmark_key = ''
    or v_benchmark_return is null
    or v_source_version = ''
    or v_source_hash !~ '^[0-9a-f]{64}$'
    or pg_catalog.jsonb_typeof(v_source_manifest) <> 'object'
    or v_source_manifest = '{}'::jsonb
    or v_observed_at > clock_timestamp() + interval '5 minutes'
  then
    raise exception 'v20_invalid_outcome_observation' using errcode = '22023';
  end if;

  select * into v_item
  from public.v20_recommendation_items i
  where i.id = v_item_id;

  if not found or v_item.horizon_days <> v_horizon_days then
    raise exception 'v20_outcome_item_horizon_mismatch' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'twss-v20-outcome:' || v_item_id::text || ':' || v_horizon_days::text,
      0
    )
  );

  v_gross_return := pg_catalog.round(
    (100 * ((v_exit_price / v_entry_price) - 1))::numeric,
    6
  );
  v_net_return := pg_catalog.round((v_gross_return - v_transaction_cost)::numeric, 6);
  v_excess_return := pg_catalog.round((v_net_return - v_benchmark_return)::numeric, 6);
  v_industry_excess_return := case
    when v_industry_return is null then null
    else pg_catalog.round((v_net_return - v_industry_return)::numeric, 6)
  end;

  v_observation_hash := pg_catalog.encode(
    extensions.digest(
      pg_catalog.jsonb_build_object(
        'recommendationItemId', v_item_id,
        'inputHash', v_item.input_hash,
        'horizonDays', v_horizon_days,
        'entryDate', v_entry_date,
        'entryPrice', v_entry_price,
        'exitDate', v_exit_date,
        'exitPrice', v_exit_price,
        'transactionCost', v_transaction_cost,
        'benchmarkKey', v_benchmark_key,
        'benchmarkReturn', v_benchmark_return,
        'industryBenchmarkKey', v_industry_benchmark_key,
        'industryReturn', v_industry_return,
        'sourceVersion', v_source_version,
        'sourceHash', v_source_hash,
        'sourceManifest', v_source_manifest,
        'mfe', (p_observation ->> 'mfe')::numeric,
        'mae', (p_observation ->> 'mae')::numeric,
        'targetHitFirst', (p_observation ->> 'targetHitFirst')::boolean,
        'calibrationRunKey', p_observation ->> 'calibrationRunKey'
      )::text,
      'sha256'
    ),
    'hex'
  );

  select o.id into v_existing_id
  from public.v20_outcome_observations o
  where o.observation_hash = v_observation_hash;

  if v_existing_id is not null then
    return pg_catalog.jsonb_build_object(
      'observationId', v_existing_id,
      'observationHash', v_observation_hash,
      'idempotent', true
    );
  end if;

  select coalesce(max(o.revision), 0) + 1
  into v_revision
  from public.v20_outcome_observations o
  where o.recommendation_item_id = v_item_id
    and o.observed_horizon_days = v_horizon_days;

  insert into public.v20_outcome_observations (
    recommendation_item_id,
    observed_horizon_days,
    revision,
    entry_date,
    entry_price,
    exit_date,
    exit_price,
    gross_return,
    transaction_cost,
    net_return,
    benchmark_key,
    benchmark_return,
    industry_benchmark_key,
    industry_return,
    excess_return_net,
    industry_excess_return_net,
    mfe,
    mae,
    target_hit_first,
    source_version,
    source_hash,
    source_manifest,
    calibration_run_key,
    observation_hash,
    observed_at
  ) values (
    v_item_id,
    v_horizon_days,
    v_revision,
    v_entry_date,
    v_entry_price,
    v_exit_date,
    v_exit_price,
    v_gross_return,
    v_transaction_cost,
    v_net_return,
    v_benchmark_key,
    v_benchmark_return,
    v_industry_benchmark_key,
    v_industry_return,
    v_excess_return,
    v_industry_excess_return,
    (p_observation ->> 'mfe')::numeric,
    (p_observation ->> 'mae')::numeric,
    (p_observation ->> 'targetHitFirst')::boolean,
    v_source_version,
    v_source_hash,
    v_source_manifest,
    nullif(pg_catalog.btrim(coalesce(p_observation ->> 'calibrationRunKey', '')), ''),
    v_observation_hash,
    v_observed_at
  )
  returning id into v_id;

  return pg_catalog.jsonb_build_object(
    'observationId', v_id,
    'recommendationItemId', v_item_id,
    'horizonDays', v_horizon_days,
    'revision', v_revision,
    'grossReturn', v_gross_return,
    'netReturn', v_net_return,
    'excessReturnNet', v_excess_return,
    'observationHash', v_observation_hash,
    'idempotent', false
  );
end;
$$;

revoke all on function public.twss_v20_append_outcome_observation(jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v20_append_outcome_observation(jsonb)
  to service_role;

create or replace function public.twss_v20_evaluate_immutable_outcomes(
  p_as_of_date date,
  p_limit integer default 200
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_limit integer := least(greatest(coalesce(p_limit, 200), 1), 500);
  v_inserted integer := 0;
begin
  if p_as_of_date is null or p_as_of_date > current_date then
    raise exception 'v20_invalid_outcome_as_of_date' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('twss-v20-immutable-outcomes:' || p_as_of_date::text, 0)
  );

  with pending_candidates as (
    select i.id
    from public.v20_recommendation_items i
    join public.v20_recommendation_runs r on r.id = i.run_id and r.status = 'published'
    where i.public_visible
      and i.is_eligible
      and i.horizon_days in (2, 3, 5, 10, 20, 40)
      and i.signal_date < p_as_of_date
      and not exists (
        select 1
        from public.v20_outcome_observations existing
        where existing.recommendation_item_id = i.id
          and existing.observed_horizon_days = i.horizon_days
      )
      and exists (
        select 1
        from (
          select p.trade_date, p.open
          from public.stock_price_history p
          where p.symbol = i.symbol
            and p.trade_date > i.signal_date
            and p.trade_date <= p_as_of_date
            and p.updated_at < (p_as_of_date + 1)::timestamptz
          order by p.trade_date
          limit i.horizon_days
        ) path
        having count(*) = i.horizon_days
          and (pg_catalog.array_agg(path.open order by path.trade_date))[1] is not null
      )
    order by i.signal_date, i.run_id, i.model_key, i.horizon_days, i.rank_position, i.symbol
    limit v_limit
  ), target_keys as (
    select distinct i.run_id, i.model_key, i.horizon_days
    from pending_candidates c
    join public.v20_recommendation_items i on i.id = c.id
  ), peer_paths as (
    select
      i.id as recommendation_item_id,
      i.run_id,
      i.symbol,
      i.model_key,
      i.horizon_days,
      i.group_name,
      i.industry,
      i.estimated_total_cost_pct,
      i.input_hash,
      i.take_profit_1,
      i.stop_loss,
      path.entry_date,
      path.entry_price,
      path.exit_date,
      path.exit_price,
      path.max_high,
      path.min_low,
      path.target_hit_date,
      path.stop_hit_date,
      path.price_sources,
      path.max_source_updated_at
    from target_keys k
    join public.v20_recommendation_items i
      on i.run_id = k.run_id
      and i.model_key = k.model_key
      and i.horizon_days = k.horizon_days
      and i.public_visible
    join lateral (
      select
        (pg_catalog.array_agg(p.trade_date order by p.trade_date))[1] as entry_date,
        (pg_catalog.array_agg(p.open order by p.trade_date))[1] as entry_price,
        (pg_catalog.array_agg(p.trade_date order by p.trade_date))[i.horizon_days] as exit_date,
        (pg_catalog.array_agg(p.close order by p.trade_date))[i.horizon_days] as exit_price,
        max(coalesce(p.high, p.close)) as max_high,
        min(coalesce(p.low, p.close)) as min_low,
        min(p.trade_date) filter (
          where i.take_profit_1 is not null and coalesce(p.high, p.close) >= i.take_profit_1
        ) as target_hit_date,
        min(p.trade_date) filter (
          where i.stop_loss is not null and coalesce(p.low, p.close) <= i.stop_loss
        ) as stop_hit_date,
        pg_catalog.array_agg(distinct p.source) as price_sources,
        max(p.updated_at) as max_source_updated_at
      from (
        select h.trade_date, h.open, h.high, h.low, h.close, h.source, h.updated_at
        from public.stock_price_history h
        where h.symbol = i.symbol
          and h.trade_date > i.signal_date
          and h.trade_date <= p_as_of_date
          and h.updated_at < (p_as_of_date + 1)::timestamptz
        order by h.trade_date
        limit i.horizon_days
      ) p
      having count(*) = i.horizon_days
        and (pg_catalog.array_agg(p.open order by p.trade_date))[1] is not null
    ) path on true
  ), peer_returns as (
    select
      p.*,
      pg_catalog.round((100 * ((p.exit_price / p.entry_price) - 1))::numeric, 6)
        as gross_return,
      pg_catalog.round(
        (100 * ((p.exit_price / p.entry_price) - 1) - p.estimated_total_cost_pct)::numeric,
        6
      ) as net_return,
      pg_catalog.round((100 * ((p.max_high / p.entry_price) - 1))::numeric, 6) as mfe,
      pg_catalog.round((100 * ((p.min_low / p.entry_price) - 1))::numeric, 6) as mae
    from peer_paths p
  ), benchmarked as (
    select
      p.*,
      avg(p.net_return) over (
        partition by p.run_id, p.model_key, p.horizon_days, p.group_name
      ) as group_benchmark_return,
      count(*) over (
        partition by p.run_id, p.model_key, p.horizon_days, p.group_name
      ) as group_peer_count,
      max(p.max_source_updated_at) over (
        partition by p.run_id, p.model_key, p.horizon_days, p.group_name
      ) as group_max_source_updated_at,
      avg(p.net_return) over (
        partition by p.run_id, p.model_key, p.horizon_days, p.group_name, pg_catalog.lower(coalesce(p.industry, ''))
      ) as industry_benchmark_return,
      count(*) over (
        partition by p.run_id, p.model_key, p.horizon_days, p.group_name, pg_catalog.lower(coalesce(p.industry, ''))
      ) as industry_peer_count,
      max(p.max_source_updated_at) over (
        partition by p.run_id, p.model_key, p.horizon_days, p.group_name, pg_catalog.lower(coalesce(p.industry, ''))
      ) as industry_max_source_updated_at
    from peer_returns p
  ), evaluated as (
    select
      b.*,
      case b.group_name
        when 'listed' then 'TWSE_EQUAL_WEIGHT_NET'
        when 'otc' then 'TPEX_EQUAL_WEIGHT_NET'
        when 'etf' then 'ETF_EQUAL_WEIGHT_NET'
      end as benchmark_key,
      case
        when nullif(pg_catalog.btrim(coalesce(b.industry, '')), '') is not null
          and b.industry_peer_count >= 5
        then 'INDUSTRY_EQUAL_WEIGHT_NET:' || pg_catalog.lower(b.industry)
        else null
      end as industry_benchmark_key,
      pg_catalog.encode(
        extensions.digest(
          pg_catalog.jsonb_build_object(
            'asOfDate', p_as_of_date,
            'recommendationItemId', b.recommendation_item_id,
            'entryDate', b.entry_date,
            'entryPrice', b.entry_price,
            'exitDate', b.exit_date,
            'exitPrice', b.exit_price,
            'priceSources', b.price_sources,
            'priceMaxUpdatedAt', b.max_source_updated_at,
            'groupName', b.group_name,
            'groupPeerCount', b.group_peer_count,
            'groupBenchmarkReturn', pg_catalog.round(b.group_benchmark_return::numeric, 6),
            'groupMaxUpdatedAt', b.group_max_source_updated_at,
            'industry', b.industry,
            'industryPeerCount', b.industry_peer_count,
            'industryBenchmarkReturn', case
              when b.industry_peer_count >= 5
              then pg_catalog.round(b.industry_benchmark_return::numeric, 6)
              else null
            end,
            'industryMaxUpdatedAt', case
              when b.industry_peer_count >= 5 then b.industry_max_source_updated_at
              else null
            end
          )::text,
          'sha256'
        ),
        'hex'
      ) as source_hash
    from benchmarked b
    join pending_candidates c on c.id = b.recommendation_item_id
    where b.group_peer_count >= 5
  ), finalized as (
    select
      e.*,
      pg_catalog.encode(
        extensions.digest(
          pg_catalog.jsonb_build_object(
            'inputHash', e.input_hash,
            'sourceHash', e.source_hash,
            'grossReturn', e.gross_return,
            'transactionCost', e.estimated_total_cost_pct,
            'netReturn', e.net_return,
            'benchmarkReturn', pg_catalog.round(e.group_benchmark_return::numeric, 6),
            'industryReturn', case
              when e.industry_peer_count >= 5
              then pg_catalog.round(e.industry_benchmark_return::numeric, 6)
              else null
            end,
            'mfe', e.mfe,
            'mae', e.mae
          )::text,
          'sha256'
        ),
        'hex'
      ) as observation_hash
    from evaluated e
  )
  insert into public.v20_outcome_observations (
    recommendation_item_id,
    observed_horizon_days,
    revision,
    entry_date,
    entry_price,
    exit_date,
    exit_price,
    gross_return,
    transaction_cost,
    net_return,
    benchmark_key,
    benchmark_return,
    industry_benchmark_key,
    industry_return,
    excess_return_net,
    industry_excess_return_net,
    mfe,
    mae,
    target_hit_first,
    source_version,
    source_hash,
    source_manifest,
    observation_hash,
    observed_at,
    recorded_at
  )
  select
    f.recommendation_item_id,
    f.horizon_days,
    1,
    f.entry_date,
    f.entry_price,
    f.exit_date,
    f.exit_price,
    f.gross_return,
    f.estimated_total_cost_pct,
    f.net_return,
    f.benchmark_key,
    pg_catalog.round(f.group_benchmark_return::numeric, 6),
    f.industry_benchmark_key,
    case
      when f.industry_peer_count >= 5
      then pg_catalog.round(f.industry_benchmark_return::numeric, 6)
      else null
    end,
    pg_catalog.round((f.net_return - f.group_benchmark_return)::numeric, 6),
    case
      when f.industry_peer_count >= 5
      then pg_catalog.round((f.net_return - f.industry_benchmark_return)::numeric, 6)
      else null
    end,
    f.mfe,
    f.mae,
    case
      when f.target_hit_date is null then false
      when f.stop_hit_date is null then true
      when f.target_hit_date < f.stop_hit_date then true
      when f.target_hit_date > f.stop_hit_date then false
      else null
    end,
    'stock_price_history-v1',
    f.source_hash,
    pg_catalog.jsonb_build_object(
      'asOfDate', p_as_of_date,
      'priceTable', 'stock_price_history',
      'priceSources', f.price_sources,
      'priceMaxUpdatedAt', f.max_source_updated_at,
      'entryRule', 'next_session_open',
      'exitRule', 'nth_session_close',
      'horizonDays', f.horizon_days,
      'groupBenchmark', pg_catalog.jsonb_build_object(
        'key', f.benchmark_key,
        'method', 'equal_weight_net_after_item_cost',
        'peerCount', f.group_peer_count,
        'maxSourceUpdatedAt', f.group_max_source_updated_at
      ),
      'industryBenchmark', case
        when f.industry_peer_count >= 5 then pg_catalog.jsonb_build_object(
          'key', f.industry_benchmark_key,
          'method', 'equal_weight_net_after_item_cost',
          'peerCount', f.industry_peer_count,
          'maxSourceUpdatedAt', f.industry_max_source_updated_at
        )
        else null
      end,
      'recommendationInputHash', f.input_hash
    ),
    f.observation_hash,
    clock_timestamp(),
    clock_timestamp()
  from finalized f
  where not exists (
    select 1
    from public.v20_outcome_observations existing
    where existing.recommendation_item_id = f.recommendation_item_id
      and existing.observed_horizon_days = f.horizon_days
  )
  order by f.entry_date, f.recommendation_item_id
  limit v_limit
  on conflict do nothing;

  get diagnostics v_inserted = row_count;

  return pg_catalog.jsonb_build_object(
    'asOfDate', p_as_of_date,
    'limit', v_limit,
    'inserted', v_inserted,
    'source', 'immutable_forward_observations',
    'entryRule', 'next_session_open',
    'exitRule', 'nth_session_close',
    'evaluatedAt', clock_timestamp()
  );
end;
$$;

revoke all on function public.twss_v20_evaluate_immutable_outcomes(date, integer)
  from public, anon, authenticated;
grant execute on function public.twss_v20_evaluate_immutable_outcomes(date, integer)
  to service_role;

comment on function public.twss_v20_evaluate_immutable_outcomes(date, integer) is
  'Bounded service-only forward evaluator: published eligible items only, next-session open to Nth close, group/industry equal-weight net benchmarks, append revision 1 only.';

create or replace function public.twss_v20_read_publication_state()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  select coalesce(
    (
      select pg_catalog.jsonb_build_object(
        'publicationPhase', 'complete',
        'publishedDataDate', r.data_date,
        'publishedAt', r.published_at,
        'runId', r.id,
        'publicationKey', r.publication_key,
        'contentHash', r.content_hash,
        'revision', r.revision,
        'dataCutoffAt', r.data_cutoff_at,
        'modelVersion', r.model_version,
        'featureVersion', r.feature_version,
        'costModelVersion', r.cost_model_version,
        'calibrationVersion', r.calibration_version,
        'codeHash', r.code_hash,
        'sourceVersion', r.source_version,
        'sourceHash', r.source_hash,
        'sourceManifest', r.source_manifest,
        'modelManifest', r.model_manifest,
        'marketContext', r.market_context_snapshot,
        'marketRegime', r.market_regime,
        'expectedSymbolCount', r.expected_symbol_count,
        'scoredSymbolCount', r.scored_symbol_count,
        'signalCount', r.signal_count,
        'publicItemCount', r.signal_count - r.research_item_count,
        'eligibleItemCount', r.eligible_item_count,
        'researchItemCount', r.research_item_count,
        'dataCompleteness', r.cycle_completeness,
        'deadletterCount', r.deadletter_count,
        'terminalErrors', r.terminal_errors
      )
      from public.v20_publication_head h
      join public.v20_recommendation_runs r on r.id = h.run_id
      where h.audience = 'public'
      limit 1
    ),
    pg_catalog.jsonb_build_object(
      'publicationPhase', 'unpublished',
      'publishedDataDate', null,
      'publishedAt', null,
      'runId', null,
      'dataCompleteness', 0
    )
  );
$$;

-- Preserve the Vercel call name while moving it from mutable worker state to
-- the immutable publication head.  It is now service-only.
create or replace function public.twss_v20_publication_state()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  select public.twss_v20_read_publication_state();
$$;

create or replace function public.twss_v20_read_rankings(p_query jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_model_key text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'modelKey', '')), '');
  v_horizon_days integer := (p_query ->> 'horizonDays')::integer;
  v_group_name text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'groupName', '')), '');
  v_industry text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'industry', '')), '');
  v_limit integer := least(
    greatest(coalesce((p_query ->> 'limit')::integer, 50), 1),
    200
  );
  v_after_rank integer := greatest(coalesce((p_query ->> 'afterRank')::integer, 0), 0);
  v_run_id bigint := (p_query ->> 'runId')::bigint;
  v_run public.v20_recommendation_runs%rowtype;
  v_total integer;
  v_remaining_count integer;
  v_page_count integer;
  v_next_after_rank integer;
  v_items jsonb;
begin
  if v_horizon_days = 60 then
    raise exception 'v20_research_horizon_not_public' using errcode = '22023';
  end if;

  if p_query is null or pg_catalog.jsonb_typeof(p_query) <> 'object'
    or (v_model_key is not null and v_model_key not in ('short', 'medium'))
    or (v_group_name is not null and v_group_name not in ('listed', 'otc', 'etf'))
    or (
      v_horizon_days is not null
      and not (
        (coalesce(v_model_key, 'short') = 'short' and v_horizon_days in (2, 3, 5, 10))
        or (coalesce(v_model_key, 'medium') = 'medium' and v_horizon_days in (10, 20, 40))
        or (v_model_key is null and v_horizon_days in (2, 3, 5, 10, 20, 40))
      )
    )
  then
    raise exception 'v20_invalid_ranking_query' using errcode = '22023';
  end if;

  if v_run_id is null then
    select h.run_id into v_run_id
    from public.v20_publication_head h
    where h.audience = 'public';
  end if;

  select * into v_run
  from public.v20_recommendation_runs r
  where r.id = v_run_id and r.status = 'published';

  if not found then
    return pg_catalog.jsonb_build_object(
      'run', null,
      'items', '[]'::jsonb,
      'total', 0,
      'hasMore', false,
      'nextAfterRank', null
    );
  end if;

  with matching as (
    select i.*
    from public.v20_recommendation_items i
    where i.run_id = v_run_id
      and i.public_visible
      and i.is_eligible
      and i.rank_position is not null
      and (v_model_key is null or i.model_key = v_model_key)
      and (v_horizon_days is null or i.horizon_days = v_horizon_days)
      and (v_group_name is null or i.group_name = v_group_name)
      and (v_industry is null or pg_catalog.lower(coalesce(i.industry, '')) = pg_catalog.lower(v_industry))
  ), filtered as (
    select * from matching where rank_position > v_after_rank
  ), page as (
    select *
    from filtered
    order by model_key, horizon_days, rank_position, symbol
    limit v_limit
  )
  select
    (select count(*)::integer from matching),
    (select count(*)::integer from filtered),
    (select count(*)::integer from page),
    (select max(rank_position)::integer from page),
    coalesce(
      (
        select pg_catalog.jsonb_agg(
          pg_catalog.jsonb_build_object(
            'recommendationItemId', p.id,
            'symbol', p.symbol,
            'name', p.name,
            'signalDate', p.signal_date,
            'modelKey', p.model_key,
            'horizonDays', p.horizon_days,
            'modelVersion', p.model_version,
            'groupName', p.group_name,
            'market', p.market,
            'industry', p.industry,
            'instrumentType', p.instrument_type,
            'strategyKey', p.strategy_key,
            'rankPosition', p.rank_position,
            'previousRank', p.previous_rank,
            'rankDelta', p.rank_delta,
            'marketPercentile', p.market_percentile,
            'rawOpportunityScore', p.raw_opportunity_score,
            'netOpportunityScore', p.net_opportunity_score,
            'opportunityScore', p.net_opportunity_score,
            'riskScore', p.risk_score,
            'confidence', p.confidence,
            'completeness', p.completeness,
            'estimatedCommissionPct', p.estimated_commission_pct,
            'estimatedTaxPct', p.estimated_tax_pct,
            'estimatedSlippagePct', p.estimated_slippage_pct,
            'estimatedSpreadPct', p.estimated_spread_pct,
            'estimatedTotalCostPct', p.estimated_total_cost_pct
          ) || pg_catalog.jsonb_build_object(
            'downsidePenaltyScore', p.downside_penalty_score,
            'turnoverPenaltyScore', p.turnover_penalty_score,
            'costPenaltyScore', p.cost_penalty_score,
            'turnoverExposure', p.turnover_exposure,
            'liquidityGrade', p.liquidity_grade,
            'opportunityState', p.opportunity_state,
            'predictionBasis', p.prediction_basis,
            'calibratedUpProbability', p.calibrated_up_probability,
            'expectedNetReturn', p.expected_return_net,
            'expectedExcessReturnGross', p.expected_excess_return_gross,
            'expectedExcessReturnNet', p.expected_excess_return_net,
            'calibrationSampleCount', p.calibration_sample_count,
            'benchmarkKey', p.benchmark_key,
            'recommendedHoldingDays', p.recommended_holding_days,
            'recommendedAction', p.recommended_action,
            'entryLow', p.entry_low,
            'entryHigh', p.entry_high,
            'breakoutPrice', p.breakout_price,
            'noChasePrice', p.no_chase_price,
            'stopLoss', p.stop_loss,
            'takeProfit1', p.take_profit_1,
            'takeProfit2', p.take_profit_2,
            'riskRewardRatio', p.risk_reward_ratio,
            'featureScores', p.feature_scores,
            'gateResults', p.gate_results,
            'reasons', p.reasons,
            'risks', p.risks,
            'invalidationConditions', p.invalidation_conditions,
            'sourceManifest', p.source_manifest,
            'inputHash', p.input_hash
          )
          order by p.model_key, p.horizon_days, p.rank_position, p.symbol
        )
        from page p
      ),
      '[]'::jsonb
    )
  into v_total, v_remaining_count, v_page_count, v_next_after_rank, v_items;

  return pg_catalog.jsonb_build_object(
    'run', pg_catalog.jsonb_build_object(
      'runId', v_run.id,
      'dataDate', v_run.data_date,
      'dataCutoffAt', v_run.data_cutoff_at,
      'revision', v_run.revision,
      'modelVersion', v_run.model_version,
      'featureVersion', v_run.feature_version,
      'costModelVersion', v_run.cost_model_version,
      'calibrationVersion', v_run.calibration_version,
      'sourceVersion', v_run.source_version,
      'sourceHash', v_run.source_hash,
      'contentHash', v_run.content_hash,
      'marketRegime', v_run.market_regime,
      'publishedAt', v_run.published_at
    ),
    'items', v_items,
    'total', v_total,
    'pageCount', v_page_count,
    'hasMore', v_remaining_count > v_page_count,
    'nextAfterRank', v_next_after_rank
  );
end;
$$;

revoke all on function public.twss_v20_read_publication_state()
  from public, anon, authenticated;
revoke all on function public.twss_v20_publication_state()
  from public, anon, authenticated;
revoke all on function public.twss_v20_read_rankings(jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v20_read_publication_state() to service_role;
grant execute on function public.twss_v20_publication_state() to service_role;
grant execute on function public.twss_v20_read_rankings(jsonb) to service_role;

create or replace function public.twss_v20_read_stock_snapshot(p_query jsonb)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_symbol text := pg_catalog.upper(pg_catalog.btrim(coalesce(p_query ->> 'symbol', '')));
  v_run_id bigint := (p_query ->> 'runId')::bigint;
  v_run public.v20_recommendation_runs%rowtype;
  v_items jsonb;
begin
  if p_query is null
    or pg_catalog.jsonb_typeof(p_query) <> 'object'
    or v_symbol !~ '^[0-9]{4,6}[A-Z]?$'
  then
    raise exception 'v20_invalid_stock_snapshot_query' using errcode = '22023';
  end if;

  if v_run_id is null then
    select h.run_id into v_run_id
    from public.v20_publication_head h
    where h.audience = 'public';
  end if;

  select * into v_run
  from public.v20_recommendation_runs r
  where r.id = v_run_id and r.status = 'published';

  if not found then
    return pg_catalog.jsonb_build_object(
      'run', null,
      'symbol', v_symbol,
      'found', false,
      'items', '[]'::jsonb
    );
  end if;

  select coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'recommendationItemId', i.id,
        'symbol', i.symbol,
        'name', i.name,
        'signalDate', i.signal_date,
        'modelKey', i.model_key,
        'horizonDays', i.horizon_days,
        'modelVersion', i.model_version,
        'groupName', i.group_name,
        'market', i.market,
        'industry', i.industry,
        'instrumentType', i.instrument_type,
        'strategyKey', i.strategy_key,
        'isEligible', i.is_eligible,
        'rankPosition', i.rank_position,
        'previousRank', i.previous_rank,
        'rankDelta', i.rank_delta,
        'marketPercentile', i.market_percentile,
        'rawOpportunityScore', i.raw_opportunity_score,
        'netOpportunityScore', i.net_opportunity_score,
        'opportunityScore', i.net_opportunity_score,
        'riskScore', i.risk_score,
        'confidence', i.confidence,
        'completeness', i.completeness,
        'estimatedCommissionPct', i.estimated_commission_pct,
        'estimatedTaxPct', i.estimated_tax_pct,
        'estimatedSlippagePct', i.estimated_slippage_pct,
        'estimatedSpreadPct', i.estimated_spread_pct,
        'estimatedTotalCostPct', i.estimated_total_cost_pct
      ) || pg_catalog.jsonb_build_object(
        'downsidePenaltyScore', i.downside_penalty_score,
        'turnoverPenaltyScore', i.turnover_penalty_score,
        'costPenaltyScore', i.cost_penalty_score,
        'turnoverExposure', i.turnover_exposure,
        'liquidityGrade', i.liquidity_grade,
        'opportunityState', i.opportunity_state,
        'predictionBasis', i.prediction_basis,
        'calibratedUpProbability', i.calibrated_up_probability,
        'expectedNetReturn', i.expected_return_net,
        'expectedExcessReturnGross', i.expected_excess_return_gross,
        'expectedExcessReturnNet', i.expected_excess_return_net,
        'calibrationSampleCount', i.calibration_sample_count,
        'benchmarkKey', i.benchmark_key,
        'recommendedHoldingDays', i.recommended_holding_days,
        'recommendedAction', i.recommended_action,
        'entryLow', i.entry_low,
        'entryHigh', i.entry_high,
        'breakoutPrice', i.breakout_price,
        'noChasePrice', i.no_chase_price,
        'stopLoss', i.stop_loss,
        'takeProfit1', i.take_profit_1,
        'takeProfit2', i.take_profit_2,
        'riskRewardRatio', i.risk_reward_ratio,
        'featureScores', i.feature_scores,
        'gateResults', i.gate_results,
        'reasons', i.reasons,
        'risks', i.risks,
        'invalidationConditions', i.invalidation_conditions,
        'sourceManifest', i.source_manifest,
        'inputHash', i.input_hash
      )
      order by i.model_key, i.horizon_days
    ),
    '[]'::jsonb
  )
  into v_items
  from public.v20_recommendation_items i
  where i.run_id = v_run_id
    and i.symbol = v_symbol
    and i.public_visible;

  return pg_catalog.jsonb_build_object(
    'run', pg_catalog.jsonb_build_object(
      'runId', v_run.id,
      'dataDate', v_run.data_date,
      'dataCutoffAt', v_run.data_cutoff_at,
      'revision', v_run.revision,
      'modelVersion', v_run.model_version,
      'featureVersion', v_run.feature_version,
      'costModelVersion', v_run.cost_model_version,
      'calibrationVersion', v_run.calibration_version,
      'sourceVersion', v_run.source_version,
      'sourceHash', v_run.source_hash,
      'contentHash', v_run.content_hash,
      'marketRegime', v_run.market_regime,
      'publishedAt', v_run.published_at
    ),
    'symbol', v_symbol,
    'found', pg_catalog.jsonb_array_length(v_items) > 0,
    'items', v_items
  );
end;
$$;

revoke all on function public.twss_v20_read_stock_snapshot(jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v20_read_stock_snapshot(jsonb)
  to service_role;

create or replace function public.twss_v20_read_validation_summary(p_query jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_model_key text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'modelKey', '')), '');
  v_horizon_days integer := (p_query ->> 'horizonDays')::integer;
  v_model_version text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'modelVersion', '')), '');
  v_strategy_key text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'strategyKey', '')), '');
  v_market_regime text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'marketRegime', '')), '');
  v_industry text := nullif(pg_catalog.btrim(coalesce(p_query ->> 'industry', '')), '');
  v_from_date date := (p_query ->> 'fromDate')::date;
  v_to_date date := (p_query ->> 'toDate')::date;
  v_top_n integer := least(
    greatest(coalesce((p_query ->> 'topN')::integer, 50), 1),
    500
  );
  v_minimum_sample_count integer := least(
    greatest(coalesce((p_query ->> 'minimumSampleCount')::integer, 100), 100),
    10000
  );
  v_sample_count integer;
  v_items jsonb;
begin
  if v_horizon_days = 60 then
    raise exception 'v20_research_horizon_not_public' using errcode = '22023';
  end if;

  if p_query is null
    or pg_catalog.jsonb_typeof(p_query) <> 'object'
    or (v_model_key is not null and v_model_key not in ('short', 'medium'))
    or (v_from_date is not null and v_to_date is not null and v_from_date > v_to_date)
    or (
      v_horizon_days is not null
      and not (
        (v_model_key = 'short' and v_horizon_days in (2, 3, 5, 10))
        or (v_model_key = 'medium' and v_horizon_days in (10, 20, 40))
        or (v_model_key is null and v_horizon_days in (2, 3, 5, 10, 20, 40))
      )
    )
  then
    raise exception 'v20_invalid_validation_query' using errcode = '22023';
  end if;

  with latest as (
    select
      o.*,
      pg_catalog.row_number() over (
        partition by o.recommendation_item_id, o.observed_horizon_days
        order by o.revision desc
      ) as observation_order
    from public.v20_outcome_observations o
  )
  select count(*)::integer
  into v_sample_count
  from latest o
  join public.v20_recommendation_items i on i.id = o.recommendation_item_id
  join public.v20_recommendation_runs r on r.id = i.run_id
  where o.observation_order = 1
    and r.status = 'published'
    and i.public_visible
    and i.is_eligible
    and i.rank_position between 1 and v_top_n
    and o.observed_horizon_days = i.horizon_days
    and (v_model_key is null or i.model_key = v_model_key)
    and (v_horizon_days is null or i.horizon_days = v_horizon_days)
    and (v_model_version is null or i.model_version = v_model_version)
    and (v_strategy_key is null or i.strategy_key = v_strategy_key)
    and (v_market_regime is null or coalesce(r.market_regime, 'unknown') = v_market_regime)
    and (v_industry is null or pg_catalog.lower(coalesce(i.industry, '')) = pg_catalog.lower(v_industry))
    and (v_from_date is null or r.data_date >= v_from_date)
    and (v_to_date is null or r.data_date <= v_to_date);

  if v_sample_count < v_minimum_sample_count then
    return pg_catalog.jsonb_build_object(
      'status', 'insufficient_data',
      'source', 'immutable_forward_observations',
      'sampleCount', v_sample_count,
      'minimumSampleCount', v_minimum_sample_count,
      'sufficient', false,
      'topN', v_top_n,
      'items', '[]'::jsonb
    );
  end if;

  with latest as (
    select
      o.*,
      pg_catalog.row_number() over (
        partition by o.recommendation_item_id, o.observed_horizon_days
        order by o.revision desc
      ) as observation_order
    from public.v20_outcome_observations o
  ), filtered as (
    select
      o.*,
      i.model_key,
      i.horizon_days,
      i.model_version,
      i.strategy_key,
      i.turnover_exposure,
      i.estimated_total_cost_pct,
      r.data_date,
      coalesce(r.market_regime, 'unknown') as market_regime
    from latest o
    join public.v20_recommendation_items i on i.id = o.recommendation_item_id
    join public.v20_recommendation_runs r on r.id = i.run_id
    where o.observation_order = 1
      and r.status = 'published'
      and i.public_visible
      and i.is_eligible
      and i.rank_position between 1 and v_top_n
      and o.observed_horizon_days = i.horizon_days
      and (v_model_key is null or i.model_key = v_model_key)
      and (v_horizon_days is null or i.horizon_days = v_horizon_days)
      and (v_model_version is null or i.model_version = v_model_version)
      and (v_strategy_key is null or i.strategy_key = v_strategy_key)
      and (v_market_regime is null or coalesce(r.market_regime, 'unknown') = v_market_regime)
      and (v_industry is null or pg_catalog.lower(coalesce(i.industry, '')) = pg_catalog.lower(v_industry))
      and (v_from_date is null or r.data_date >= v_from_date)
      and (v_to_date is null or r.data_date <= v_to_date)
  ), buckets as (
    select
      f.model_key,
      f.horizon_days,
      f.model_version,
      f.strategy_key,
      f.market_regime,
      count(*)::integer as sample_count,
      pg_catalog.round((100 * avg(case when f.net_return > 0 then 1 else 0 end))::numeric, 2)
        as cost_after_win_rate,
      pg_catalog.round((100 * avg(case when f.excess_return_net > 0 then 1 else 0 end))::numeric, 2)
        as excess_win_rate,
      pg_catalog.round(avg(f.gross_return)::numeric, 4) as average_gross_return,
      pg_catalog.round(avg(f.net_return)::numeric, 4) as average_net_return,
      pg_catalog.round(avg(f.excess_return_net)::numeric, 4) as average_excess_return_net,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.5) within group (order by f.net_return))::numeric,
        4
      ) as median_net_return,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.1) within group (order by f.net_return))::numeric,
        4
      ) as return_p10,
      pg_catalog.round(
        (pg_catalog.percentile_cont(0.9) within group (order by f.net_return))::numeric,
        4
      ) as return_p90,
      pg_catalog.round(avg(f.mfe)::numeric, 4) as average_mfe,
      pg_catalog.round(avg(f.mae)::numeric, 4) as average_mae,
      pg_catalog.round(avg(f.transaction_cost)::numeric, 4) as average_realized_cost,
      pg_catalog.round(avg(f.estimated_total_cost_pct)::numeric, 4) as average_estimated_cost,
      pg_catalog.round(avg(f.turnover_exposure)::numeric, 4) as average_turnover_exposure,
      pg_catalog.round(
        (
          avg(f.net_return)
          - 1.96 * coalesce(pg_catalog.stddev_samp(f.net_return), 0)
            / pg_catalog.sqrt(count(*)::numeric)
        )::numeric,
        4
      ) as mean_net_return_ci95_low,
      pg_catalog.round(
        (
          avg(f.net_return)
          + 1.96 * coalesce(pg_catalog.stddev_samp(f.net_return), 0)
            / pg_catalog.sqrt(count(*)::numeric)
        )::numeric,
        4
      ) as mean_net_return_ci95_high,
      min(f.data_date) as first_data_date,
      max(f.data_date) as last_data_date,
      max(f.observed_at) as generated_at
    from filtered f
    group by f.model_key, f.horizon_days, f.model_version, f.strategy_key, f.market_regime
    having count(*) >= v_minimum_sample_count
  ), cohort_returns as (
    -- A cohort is one publication date's equal-weight top-N realized result.
    -- This is intentionally labelled as a realized-cohort curve: the stored
    -- endpoint observations cannot reconstruct daily mark-to-market portfolio
    -- equity and must not be presented as such.
    select
      f.model_key,
      f.horizon_days,
      f.model_version,
      f.strategy_key,
      f.market_regime,
      f.data_date,
      avg(f.net_return)::numeric as cohort_net_return
    from filtered f
    group by
      f.model_key,
      f.horizon_days,
      f.model_version,
      f.strategy_key,
      f.market_regime,
      f.data_date
  ), cohort_equity as (
    select
      c.*,
      pg_catalog.exp(
        sum(
          pg_catalog.ln(
            greatest(0.000001::numeric, 1::numeric + c.cohort_net_return / 100::numeric)
          )
        ) over (
          partition by c.model_key, c.horizon_days, c.model_version, c.strategy_key, c.market_regime
          order by c.data_date
          rows between unbounded preceding and current row
        )
      )::numeric as equity
    from cohort_returns c
  ), cohort_peaks as (
    select
      e.*,
      greatest(
        1::numeric,
        max(e.equity) over (
          partition by e.model_key, e.horizon_days, e.model_version, e.strategy_key, e.market_regime
          order by e.data_date
          rows between unbounded preceding and current row
        )
      ) as peak_equity
    from cohort_equity e
  ), bucket_drawdowns as (
    select
      p.model_key,
      p.horizon_days,
      p.model_version,
      p.strategy_key,
      p.market_regime,
      pg_catalog.round(
        pg_catalog.abs(
          least(
            0::numeric,
            min(100::numeric * (p.equity / nullif(p.peak_equity, 0) - 1::numeric))
          )
        ),
        4
      ) as max_realized_cohort_drawdown
    from cohort_peaks p
    group by p.model_key, p.horizon_days, p.model_version, p.strategy_key, p.market_regime
  )
  select coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'modelKey', b.model_key,
        'horizonDays', b.horizon_days,
        'modelVersion', b.model_version,
        'strategyKey', b.strategy_key,
        'marketRegime', b.market_regime,
        'sampleCount', b.sample_count,
        'costAfterWinRate', b.cost_after_win_rate,
        'excessWinRate', b.excess_win_rate,
        'averageGrossReturn', b.average_gross_return,
        'averageNetReturn', b.average_net_return,
        'averageExcessReturnNet', b.average_excess_return_net,
        'medianNetReturn', b.median_net_return,
        'returnP10', b.return_p10,
        'returnP90', b.return_p90,
        'averageMfe', b.average_mfe,
        'averageMae', b.average_mae,
        'averageRealizedCost', b.average_realized_cost,
        'averageEstimatedCost', b.average_estimated_cost,
        'averageTurnoverExposure', b.average_turnover_exposure,
        'maxRealizedCohortDrawdown', d.max_realized_cohort_drawdown,
        'meanNetReturnCi95Low', b.mean_net_return_ci95_low,
        'meanNetReturnCi95High', b.mean_net_return_ci95_high,
        'firstDataDate', b.first_data_date,
        'lastDataDate', b.last_data_date,
        'generatedAt', b.generated_at
      )
      order by b.model_key, b.horizon_days, b.model_version, b.strategy_key, b.market_regime
    ),
    '[]'::jsonb
  ) into v_items
  from buckets b
  left join bucket_drawdowns d
    on d.model_key = b.model_key
    and d.horizon_days = b.horizon_days
    and d.model_version = b.model_version
    and d.strategy_key = b.strategy_key
    and d.market_regime = b.market_regime;

  if pg_catalog.jsonb_array_length(v_items) = 0 then
    return pg_catalog.jsonb_build_object(
      'status', 'insufficient_data',
      'source', 'immutable_forward_observations',
      'sampleCount', v_sample_count,
      'minimumSampleCount', v_minimum_sample_count,
      'sufficient', false,
      'topN', v_top_n,
      'items', '[]'::jsonb
    );
  end if;

  return pg_catalog.jsonb_build_object(
    'status', 'ready',
    'source', 'immutable_forward_observations',
    'sampleCount', v_sample_count,
    'minimumSampleCount', v_minimum_sample_count,
    'sufficient', true,
    'topN', v_top_n,
    'items', v_items
  );
end;
$$;

revoke all on function public.twss_v20_read_validation_summary(jsonb)
  from public, anon, authenticated;
grant execute on function public.twss_v20_read_validation_summary(jsonb)
  to service_role;

comment on function public.twss_v20_read_validation_summary(jsonb) is
  'Service-only validation read model built exclusively from latest revisions of immutable forward observations; it never mixes legacy backtests.';
