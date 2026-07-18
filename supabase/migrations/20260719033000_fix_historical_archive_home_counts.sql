begin;

set local search_path = pg_catalog, public, extensions;

create or replace function market_data.refresh_home_data_status()
returns void
language plpgsql
security invoker
set search_path = pg_catalog, public, market_data
as $function$
declare
  archived_rows bigint;
  archived_parsed bigint;
  archived_quarantined bigint;
  unarchived_rows bigint;
  unarchived_parsed bigint;
  unarchived_quarantined bigint;
  latest_archive_available_at timestamptz;
begin
  perform market_data.refresh_home_data_status_without_archive();

  -- One logical queue slice can have multiple immutable payload revisions.
  -- Count only its latest archived snapshot so retries and upstream revisions
  -- do not inflate the homepage coverage summary.
  with latest_archive_slice as (
    select distinct on (
      provider_code,
      source_dataset,
      scheduled_market,
      asset_type,
      source_symbol,
      requested_start_date,
      requested_end_date
    )
      row_count,
      parsed_row_count,
      quarantined_row_count,
      first_observed_at
    from market_data.historical_archive_objects
    order by
      provider_code,
      source_dataset,
      scheduled_market,
      asset_type,
      source_symbol,
      requested_start_date,
      requested_end_date,
      created_at desc,
      archive_id desc
  )
  select
    coalesce(sum(row_count), 0),
    coalesce(sum(parsed_row_count), 0),
    coalesce(sum(quarantined_row_count), 0),
    max(first_observed_at)
  into
    archived_rows,
    archived_parsed,
    archived_quarantined,
    latest_archive_available_at
  from latest_archive_slice;

  select
    count(*),
    count(*) filter (where landing.parse_status = 'PARSED'),
    count(*) filter (where landing.parse_status = 'QUARANTINED')
  into unarchived_rows, unarchived_parsed, unarchived_quarantined
  from market_data.historical_daily_bar_landing as landing
  where not exists (
    select 1
    from market_data.historical_archive_objects as archive
    where archive.provider_code = 'FINMIND'
      and archive.source_dataset = landing.source_dataset
      and archive.source_payload_hash = landing.source_payload_hash
  );

  update public.home_data_status
  set
    latest_available_at = greatest(
      home_data_status.latest_available_at,
      latest_archive_available_at
    ),
    historical_landing_count = unarchived_rows + archived_rows,
    historical_parsed_count = unarchived_parsed + archived_parsed,
    historical_quarantined_count = unarchived_quarantined + archived_quarantined,
    reason_codes = case
      when unarchived_rows + archived_rows > 0
        and historical_production_eligible_count = 0
        and not ('HISTORICAL_POINT_IN_TIME_UNVERIFIED' = any(reason_codes))
      then array_append(reason_codes, 'HISTORICAL_POINT_IN_TIME_UNVERIFIED')
      else reason_codes
    end,
    updated_at = statement_timestamp()
  where status_key = 'latest';
end
$function$;

revoke all on function market_data.refresh_home_data_status()
from public, anon, authenticated;
grant execute on function market_data.refresh_home_data_status()
to service_role;

select market_data.refresh_home_data_status();

commit;

notify pgrst, 'reload schema';
