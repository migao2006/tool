begin;

set local search_path = pg_catalog, public, extensions;

alter table market_data.historical_backfill_tasks
drop constraint if exists historical_backfill_task_identity_check;
alter table market_data.historical_backfill_tasks
add constraint historical_backfill_task_identity_check check (
    nullif(btrim(source_dataset), '') is not null
    and nullif(btrim(source_symbol), '') is not null
    and length(source_symbol) <= 32
    and (
        (
            asset_type = 'COMMON_STOCK'
            and (
                (
                    selection_basis = 'CURRENT_SECURITY_MASTER_SCHEDULING_ONLY'
                    and security_id is not null
                )
                or (
                    selection_basis
                    = 'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
                    and security_id is null
                )
            )
        )
        or asset_type = 'ETF'
    )
);

alter table market_data.historical_backfill_tasks
drop constraint if exists historical_backfill_task_research_scope_check;
alter table market_data.historical_backfill_tasks
add constraint historical_backfill_task_research_scope_check check (
    selection_basis in (
        'CURRENT_SECURITY_MASTER_SCHEDULING_ONLY',
        'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
    )
    and usage_scope = 'RAW_LANDING_ONLY'
    and system_status = 'RESEARCH_ONLY'
    and 'REQUEST_UNIVERSE_NOT_POINT_IN_TIME' = any(reason_codes)
    and (
        selection_basis <> 'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
        or (
            asset_type = 'COMMON_STOCK'
            and security_id is null
            and 'IDENTITY_UNRESOLVED' = any(reason_codes)
            and 'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
            = any(reason_codes)
        )
    )
);

create or replace function
market_data.seed_historical_backfill_delisted_common_tasks(
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

  with candidates as materialized (
    select distinct on (
      observation.listing_market,
      observation.source_symbol,
      observation.termination_date
    )
      observation.listing_market as market,
      observation.source_symbol,
      observation.source_name,
      observation.termination_date
    from market_data.delisting_registry_observations as observation
    where observation.termination_date between p_start_date and p_end_date
      and observation.source_symbol ~ '^[0-9]{4}$'
      and observation.source_symbol !~ '^(00|91)'
      and observation.first_observed_at <= p_selection_snapshot_at
      and observation.available_at <= p_selection_snapshot_at
      and observation.record_status = 'VERIFIED_DELISTING'
      and observation.identity_resolution_status = 'UNRESOLVED'
      and observation.usage_scope = 'IDENTITY_RESEARCH_ONLY'
      and observation.system_status = 'RESEARCH_ONLY'
    order by
      observation.listing_market,
      observation.source_symbol,
      observation.termination_date,
      observation.first_observed_at desc,
      observation.delisting_observation_id desc
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
    selection_basis,
    usage_scope,
    system_status,
    reason_codes
  )
  select
    'FINMIND',
    'daily_bars',
    null,
    candidate.source_symbol,
    candidate.source_name,
    candidate.market,
    'COMMON_STOCK',
    p_start_date,
    candidate.termination_date,
    p_selection_snapshot_at,
    'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY',
    'RAW_LANDING_ONLY',
    'RESEARCH_ONLY',
    array[
      'REQUEST_UNIVERSE_NOT_POINT_IN_TIME',
      'HISTORICAL_VINTAGE_UNAVAILABLE',
      'IDENTITY_UNRESOLVED',
      'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY',
      'RAW_LANDING_ONLY'
    ]::text[]
  from candidates as candidate
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

comment on function market_data.seed_historical_backfill_delisted_common_tasks(
    date,
    date,
    timestamptz
) is
'Seeds raw-only daily-bar tasks from unresolved official delisting
observations.
Only the ordinary-stock code contract is accepted; the source symbol remains
unlinked to the current security master.';

revoke all on function
market_data.seed_historical_backfill_delisted_common_tasks(
    date,
    date,
    timestamptz
) from public, anon, authenticated;
grant execute on function
market_data.seed_historical_backfill_delisted_common_tasks(
    date,
    date,
    timestamptz
) to service_role;

commit;

notify pgrst, 'reload schema';
