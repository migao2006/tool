begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

alter table market_data.historical_archive_objects
drop constraint historical_archive_scope_check;

alter table market_data.historical_archive_objects
add constraint historical_archive_scope_check check (
    storage_provider = 'CLOUDFLARE_R2'
    and provider_code = 'FINMIND'
    and source_dataset in (
        'daily_bars',
        'adjusted_bars',
        'institutional_flows',
        'margin_short'
    )
    and schema_version = case source_dataset
        when 'daily_bars' then 'historical_daily_bars.v1'
        when 'adjusted_bars' then 'historical_adjusted_bars.v1'
        when 'institutional_flows' then 'historical_institutional_flows.v1'
        when 'margin_short' then 'historical_margin_short.v1'
    end
    and scheduled_market in ('TWSE', 'TPEX')
    and asset_type in ('COMMON_STOCK', 'ETF')
    and requested_start_date <= requested_end_date
    and requested_start_date <= min_trade_date
    and min_trade_date <= max_trade_date
    and max_trade_date <= requested_end_date
    and point_in_time_status = 'UNVERIFIED'
    and usage_scope = 'RAW_LANDING_ONLY'
    and system_status = 'RESEARCH_ONLY'
) not valid;

alter table market_data.historical_archive_objects
validate constraint historical_archive_scope_check;

-- noqa: disable=PG01
create index if not exists historical_backfill_supplemental_claim_idx
on market_data.historical_backfill_tasks (
    provider_code,
    source_dataset,
    status,
    next_attempt_at,
    requested_start_date,
    task_id
)
where source_dataset in (
    'adjusted_bars',
    'institutional_flows',
    'margin_short'
) and market = 'TWSE' and asset_type = 'COMMON_STOCK';
-- noqa: enable=PG01

create or replace function market_data.seed_historical_supplemental_twse_tasks(
    p_start_date date,
    p_end_date date,
    p_selection_snapshot_at timestamptz
)
returns integer
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
  inserted_count integer;
begin
  if p_start_date is null
     or p_end_date is null
     or p_selection_snapshot_at is null
     or p_start_date > p_end_date then
    raise exception using
      errcode = '22023',
      message = 'valid start, end and selection snapshot are required';
  end if;

  with requested_datasets(source_dataset) as (
    values
      ('adjusted_bars'::text),
      ('institutional_flows'::text),
      ('margin_short'::text)
  ), candidates as materialized (
    select
      security.security_id,
      security.symbol,
      security.display_name,
      requested_datasets.source_dataset,
      greatest(p_start_date, coalesce(security.listing_date, p_start_date))
        as range_start,
      least(p_end_date, coalesce(security.delisting_date, p_end_date))
        as range_end
    from market_data.securities as security
    cross join requested_datasets
    where security.asset_type = 'COMMON_STOCK'
      and security.market = 'TWSE'
  ), coverage as (
    select
      candidate.*,
      exists (
        select 1
        from market_data.historical_archive_objects as archive
        where archive.provider_code = 'FINMIND'
          and archive.source_dataset = candidate.source_dataset
          and archive.source_symbol = candidate.symbol
          and archive.scheduled_market = 'TWSE'
          and archive.asset_type = 'COMMON_STOCK'
          and archive.requested_start_date <= candidate.range_start
          and archive.requested_end_date >= candidate.range_end
      ) as already_archived
    from candidates as candidate
    where candidate.range_start <= candidate.range_end
  )
  insert into market_data.historical_backfill_tasks (
    provider_code,
    source_dataset,
    security_id,
    source_symbol,
    display_name,
    market,
    asset_type,
    requested_start_date,
    requested_end_date,
    selection_snapshot_at,
    status,
    latest_completed_trade_date,
    completed_at,
    last_result_code
  )
  select
    'FINMIND',
    coverage.source_dataset,
    coverage.security_id,
    coverage.symbol,
    coverage.display_name,
    'TWSE',
    'COMMON_STOCK',
    coverage.range_start,
    coverage.range_end,
    p_selection_snapshot_at,
    case when coverage.already_archived then 'SUCCEEDED' else 'PENDING' end,
    case when coverage.already_archived then coverage.range_end else null end,
    case when coverage.already_archived then now() else null end,
    case when coverage.already_archived then 'PREEXISTING_R2_ARCHIVE' else null end
  from coverage
  on conflict (
    provider_code,
    source_dataset,
    market,
    source_symbol,
    requested_start_date,
    requested_end_date
  ) do nothing;

  get diagnostics inserted_count = row_count;
  return inserted_count;
end
$function$;


comment on function market_data.seed_historical_supplemental_twse_tasks(
    date,
    date,
    timestamptz
) is 'Seeds current TWSE common stocks as research-only scheduling aids.';
revoke all on function market_data.seed_historical_supplemental_twse_tasks(
    date,
    date,
    timestamptz
) from public, anon, authenticated;
grant execute on function market_data.seed_historical_supplemental_twse_tasks(
    date,
    date,
    timestamptz
) to service_role;

notify pgrst, 'reload schema';

commit;
