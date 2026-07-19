begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create or replace function market_data.historical_backfill_snapshot(
    p_start_date date,
    p_end_date date
)
returns table (
    database_bytes bigint,
    landing_bytes bigint,
    landing_symbols bigint,
    task_count bigint,
    twse_common_remaining bigint,
    tpex_common_remaining bigint,
    etf_task_count bigint,
    etf_remaining bigint,
    succeeded bigint,
    exhausted bigint
)
language sql
stable
security invoker
set search_path = pg_catalog, market_data
as $function$
  select
    pg_database_size(current_database()),
    pg_total_relation_size('market_data.historical_daily_bar_landing'),
    count(distinct tasks.source_symbol) filter (where tasks.status = 'SUCCEEDED'),
    count(*),
    count(*) filter (
      where tasks.asset_type = 'COMMON_STOCK'
        and tasks.market = 'TWSE'
        and tasks.status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (
      where tasks.asset_type = 'COMMON_STOCK'
        and tasks.market = 'TPEX'
        and tasks.status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (where tasks.asset_type = 'ETF'),
    count(*) filter (
      where tasks.asset_type = 'ETF'
        and tasks.status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (where tasks.status = 'SUCCEEDED'),
    count(*) filter (where tasks.status = 'EXHAUSTED')
  from market_data.historical_backfill_tasks as tasks
  where tasks.source_dataset = 'daily_bars'
    and tasks.requested_start_date >= p_start_date
    and tasks.requested_end_date <= p_end_date;
$function$;

create or replace function
market_data.historical_supplemental_backfill_snapshot(
    p_start_date date,
    p_end_date date
)
returns table (
    task_count bigint,
    adjusted_bars_remaining bigint,
    institutional_flows_remaining bigint,
    margin_short_remaining bigint,
    succeeded bigint,
    exhausted bigint
)
language sql
stable
security invoker
set search_path = pg_catalog, market_data
as $function$
  select
    count(*),
    count(*) filter (
      where tasks.source_dataset = 'adjusted_bars'
        and tasks.status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (
      where tasks.source_dataset = 'institutional_flows'
        and tasks.status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (
      where tasks.source_dataset = 'margin_short'
        and tasks.status in ('PENDING', 'LEASED', 'RETRY')
    ),
    count(*) filter (where tasks.status = 'SUCCEEDED'),
    count(*) filter (where tasks.status = 'EXHAUSTED')
  from market_data.historical_backfill_tasks as tasks
  where tasks.source_dataset in (
      'adjusted_bars', 'institutional_flows', 'margin_short'
    )
    and tasks.market = 'TWSE'
    and tasks.asset_type = 'COMMON_STOCK'
    and tasks.requested_start_date >= p_start_date
    and tasks.requested_end_date <= p_end_date;
$function$;

revoke all on function market_data.historical_supplemental_backfill_snapshot(
    date, date
) from public, anon, authenticated;
grant execute on function market_data.historical_supplemental_backfill_snapshot(
    date, date
) to service_role;

notify pgrst, 'reload schema';

commit;
