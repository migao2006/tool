begin;

create table if not exists public.home_data_status (
  status_key text primary key,
  contract_version text not null,
  as_of_date date,
  latest_available_at timestamptz,
  securities_count bigint not null default 0,
  twse_securities_count bigint not null default 0,
  tpex_securities_count bigint not null default 0,
  daily_bars_latest_date date,
  daily_bars_latest_count bigint not null default 0,
  twse_daily_bars_latest_count bigint not null default 0,
  tpex_daily_bars_latest_count bigint not null default 0,
  production_ready_daily_bars_count bigint not null default 0,
  historical_landing_count bigint not null default 0,
  historical_parsed_count bigint not null default 0,
  historical_quarantined_count bigint not null default 0,
  historical_production_eligible_count bigint not null default 0,
  trading_calendar_count bigint not null default 0,
  trading_calendar_start_date date,
  trading_calendar_end_date date,
  market_observations_count bigint not null default 0,
  corporate_actions_count bigint not null default 0,
  delisting_observations_count bigint not null default 0,
  data_sources_count bigint not null default 0,
  source_codes text[] not null default '{}',
  prediction_runs_count bigint not null default 0,
  stock_predictions_count bigint not null default 0,
  market_predictions_count bigint not null default 0,
  model_output_status text not null,
  reason_codes text[] not null default '{}',
  updated_at timestamptz not null default now(),
  constraint home_data_status_singleton_check check (status_key = 'latest'),
  constraint home_data_status_contract_check check (
    contract_version = 'home-data-status.v1'
  ),
  constraint home_data_status_model_output_status_check check (
    model_output_status in ('PASS', 'RESEARCH_ONLY', 'FAIL')
  ),
  constraint home_data_status_nonnegative_counts_check check (
    securities_count >= 0
    and twse_securities_count >= 0
    and tpex_securities_count >= 0
    and daily_bars_latest_count >= 0
    and twse_daily_bars_latest_count >= 0
    and tpex_daily_bars_latest_count >= 0
    and production_ready_daily_bars_count >= 0
    and historical_landing_count >= 0
    and historical_parsed_count >= 0
    and historical_quarantined_count >= 0
    and historical_production_eligible_count >= 0
    and trading_calendar_count >= 0
    and market_observations_count >= 0
    and corporate_actions_count >= 0
    and delisting_observations_count >= 0
    and data_sources_count >= 0
    and prediction_runs_count >= 0
    and stock_predictions_count >= 0
    and market_predictions_count >= 0
  )
);

comment on table public.home_data_status is
  'Public, read-only aggregate inventory for the homepage. It never exposes raw market_data rows or model outputs.';
comment on column public.home_data_status.as_of_date is
  'Latest imported daily-bar trade date; this is not a model decision date.';
comment on column public.home_data_status.historical_landing_count is
  'Raw landing rows only. These rows are not automatically eligible for training or recommendations.';

alter table public.home_data_status enable row level security;

revoke all on table public.home_data_status from public, anon, authenticated;
grant select on table public.home_data_status to anon, authenticated;
grant select, insert, update on table public.home_data_status to service_role;

drop policy if exists home_data_status_public_read on public.home_data_status;
create policy home_data_status_public_read
on public.home_data_status
for select
to anon, authenticated
using (true);

create or replace function market_data.refresh_home_data_status()
returns void
language plpgsql
security invoker
set search_path = pg_catalog, public, market_data
as $$
begin
  -- Serialize the cache refresh so an older concurrent snapshot cannot
  -- overwrite a newer one after both sessions finish their aggregation.
  perform pg_advisory_xact_lock(
    hashtextextended('market_data.refresh_home_data_status', 0)
  );

  with latest_trade as (
    select max(trade_date) as trade_date
    from market_data.daily_bars
  ),
  security_summary as (
    select
      count(*)::bigint as total_count,
      count(*) filter (where market = 'TWSE')::bigint as twse_count,
      count(*) filter (where market = 'TPEX')::bigint as tpex_count
    from market_data.securities
  ),
  daily_summary as (
    select
      latest_trade.trade_date,
      count(distinct daily_bars.security_id)::bigint as total_count,
      count(distinct daily_bars.security_id) filter (where securities.market = 'TWSE')::bigint
        as twse_count,
      count(distinct daily_bars.security_id) filter (where securities.market = 'TPEX')::bigint
        as tpex_count,
      count(distinct daily_bars.security_id) filter (
        where daily_bars.company_action_complete
          and daily_bars.opening_trade_available
          and daily_bars.closing_trade_available
      )::bigint as production_ready_count
    from latest_trade
    left join market_data.daily_bars
      on daily_bars.trade_date = latest_trade.trade_date
    left join market_data.securities
      on securities.security_id = daily_bars.security_id
    group by latest_trade.trade_date
  ),
  landing_summary as (
    select
      count(*)::bigint as total_count,
      count(*) filter (where parse_status = 'PARSED')::bigint as parsed_count,
      count(*) filter (where parse_status = 'QUARANTINED')::bigint as quarantined_count,
      count(*) filter (where usage_scope = 'PRODUCTION_ELIGIBLE')::bigint
        as production_eligible_count
    from market_data.historical_daily_bar_landing
  ),
  calendar_summary as (
    select
      count(*)::bigint as total_count,
      min(trading_date) as start_date,
      max(trading_date) as end_date
    from market_data.trading_calendar
  ),
  source_summary as (
    select
      count(*) filter (where is_active)::bigint as total_count,
      coalesce(
        array_agg(source_code order by source_code) filter (where is_active),
        '{}'::text[]
      ) as source_codes
    from market_data.data_sources
  ),
  latest_run as (
    select
      prediction_run_id,
      system_validation_status,
      candidate_count,
      watch_count,
      no_trade_count,
      hard_fail_count
    from market_data.prediction_runs
    where horizon = 5
    order by decision_at desc, prediction_run_id desc
    limit 1
  ),
  output_summary as (
    select
      (
        select count(*)
        from market_data.prediction_runs
        where horizon = 5
      )::bigint as prediction_runs_count,
      (
        select count(*)
        from market_data.stock_predictions
        where prediction_run_id = (
          select prediction_run_id from latest_run
        )
      )::bigint as stock_predictions_count,
      (
        select count(*)
        from market_data.market_predictions
        where prediction_run_id = (
          select prediction_run_id from latest_run
        )
      )::bigint as market_predictions_count,
      (
        select count(*)
        from market_data.data_quality_audits
        where prediction_run_id = (
          select prediction_run_id from latest_run
        )
          and hard_fail
      )::bigint as hard_fail_audit_count
  ),
  availability_summary as (
    select max(value) as latest_available_at
    from (
      values
        ((select max(available_at) from market_data.daily_bars)),
        ((select max(available_at) from market_data.market_observations)),
        ((select max(available_at) from market_data.corporate_actions)),
        ((select max(available_at) from market_data.historical_daily_bar_landing)),
        ((select max(available_at) from market_data.delisting_registry_observations))
    ) as availability(value)
  )
  insert into public.home_data_status (
    status_key,
    contract_version,
    as_of_date,
    latest_available_at,
    securities_count,
    twse_securities_count,
    tpex_securities_count,
    daily_bars_latest_date,
    daily_bars_latest_count,
    twse_daily_bars_latest_count,
    tpex_daily_bars_latest_count,
    production_ready_daily_bars_count,
    historical_landing_count,
    historical_parsed_count,
    historical_quarantined_count,
    historical_production_eligible_count,
    trading_calendar_count,
    trading_calendar_start_date,
    trading_calendar_end_date,
    market_observations_count,
    corporate_actions_count,
    delisting_observations_count,
    data_sources_count,
    source_codes,
    prediction_runs_count,
    stock_predictions_count,
    market_predictions_count,
    model_output_status,
    reason_codes,
    updated_at
  )
  select
    'latest',
    'home-data-status.v1',
    daily_summary.trade_date,
    availability_summary.latest_available_at,
    security_summary.total_count,
    security_summary.twse_count,
    security_summary.tpex_count,
    daily_summary.trade_date,
    daily_summary.total_count,
    daily_summary.twse_count,
    daily_summary.tpex_count,
    daily_summary.production_ready_count,
    landing_summary.total_count,
    landing_summary.parsed_count,
    landing_summary.quarantined_count,
    landing_summary.production_eligible_count,
    calendar_summary.total_count,
    calendar_summary.start_date,
    calendar_summary.end_date,
    (select count(*) from market_data.market_observations),
    (select count(*) from market_data.corporate_actions),
    (select count(*) from market_data.delisting_registry_observations),
    source_summary.total_count,
    source_summary.source_codes,
    output_summary.prediction_runs_count,
    output_summary.stock_predictions_count,
    output_summary.market_predictions_count,
    case
      when latest_run.prediction_run_id is null then 'RESEARCH_ONLY'
      when latest_run.system_validation_status = 'FAIL' then 'FAIL'
      when latest_run.system_validation_status = 'PASS'
        and output_summary.stock_predictions_count = (
          latest_run.candidate_count
          + latest_run.watch_count
          + latest_run.no_trade_count
        )
        and output_summary.hard_fail_audit_count = latest_run.hard_fail_count
        and output_summary.market_predictions_count = 2
        and (
          output_summary.stock_predictions_count
          + output_summary.hard_fail_audit_count
        ) > 0
        then 'PASS'
      else 'RESEARCH_ONLY'
    end,
    array_remove(
      array[
        case
          when latest_run.prediction_run_id is null
            then 'MODEL_OUTPUT_NOT_AVAILABLE'
        end,
        case
          when latest_run.prediction_run_id is not null
            and latest_run.system_validation_status = 'PASS'
            and not (
              output_summary.stock_predictions_count = (
                latest_run.candidate_count
                + latest_run.watch_count
                + latest_run.no_trade_count
              )
              and output_summary.hard_fail_audit_count = latest_run.hard_fail_count
              and output_summary.market_predictions_count = 2
              and (
                output_summary.stock_predictions_count
                + output_summary.hard_fail_audit_count
              ) > 0
            )
            then 'MODEL_OUTPUT_INCOMPLETE'
        end,
        case
          when latest_run.system_validation_status in ('RESEARCH_ONLY', 'FAIL')
            then 'MODEL_OUTPUT_' || latest_run.system_validation_status
        end,
        case
          when landing_summary.total_count > 0
            and landing_summary.production_eligible_count = 0
            then 'HISTORICAL_POINT_IN_TIME_UNVERIFIED'
        end,
        case
          when daily_summary.total_count > daily_summary.production_ready_count
            then 'EXECUTION_FLAGS_INCOMPLETE'
        end
      ]::text[],
      null
    ),
    statement_timestamp()
  from security_summary
  cross join daily_summary
  cross join landing_summary
  cross join calendar_summary
  cross join source_summary
  cross join output_summary
  cross join availability_summary
  left join latest_run on true
  on conflict (status_key) do update set
    contract_version = excluded.contract_version,
    as_of_date = excluded.as_of_date,
    latest_available_at = excluded.latest_available_at,
    securities_count = excluded.securities_count,
    twse_securities_count = excluded.twse_securities_count,
    tpex_securities_count = excluded.tpex_securities_count,
    daily_bars_latest_date = excluded.daily_bars_latest_date,
    daily_bars_latest_count = excluded.daily_bars_latest_count,
    twse_daily_bars_latest_count = excluded.twse_daily_bars_latest_count,
    tpex_daily_bars_latest_count = excluded.tpex_daily_bars_latest_count,
    production_ready_daily_bars_count = excluded.production_ready_daily_bars_count,
    historical_landing_count = excluded.historical_landing_count,
    historical_parsed_count = excluded.historical_parsed_count,
    historical_quarantined_count = excluded.historical_quarantined_count,
    historical_production_eligible_count = excluded.historical_production_eligible_count,
    trading_calendar_count = excluded.trading_calendar_count,
    trading_calendar_start_date = excluded.trading_calendar_start_date,
    trading_calendar_end_date = excluded.trading_calendar_end_date,
    market_observations_count = excluded.market_observations_count,
    corporate_actions_count = excluded.corporate_actions_count,
    delisting_observations_count = excluded.delisting_observations_count,
    data_sources_count = excluded.data_sources_count,
    source_codes = excluded.source_codes,
    prediction_runs_count = excluded.prediction_runs_count,
    stock_predictions_count = excluded.stock_predictions_count,
    market_predictions_count = excluded.market_predictions_count,
    model_output_status = excluded.model_output_status,
    reason_codes = excluded.reason_codes,
    updated_at = excluded.updated_at;
end;
$$;

revoke all on function market_data.refresh_home_data_status() from public, anon, authenticated;
grant execute on function market_data.refresh_home_data_status() to service_role;

select market_data.refresh_home_data_status();

commit;

notify pgrst, 'reload schema';
