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
        'margin_short',
        'benchmark_total_return'
    )
    and schema_version = case source_dataset
        when 'daily_bars' then 'historical_daily_bars.v1'
        when 'adjusted_bars' then 'historical_adjusted_bars.v1'
        when 'institutional_flows' then 'historical_institutional_flows.v1'
        when 'margin_short' then 'historical_margin_short.v1'
        when 'benchmark_total_return'
            then 'historical_benchmark_total_return.v1'
    end
    and scheduled_market in ('TWSE', 'TPEX')
    and (
        (
            source_dataset = 'benchmark_total_return'
            and scheduled_market = 'TWSE'
            and asset_type = 'BENCHMARK'
            and source_symbol = 'TAIEX'
        )
        or (
            source_dataset != 'benchmark_total_return'
            and asset_type in ('COMMON_STOCK', 'ETF')
        )
    )
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

alter table market_data.historical_backfill_tasks
drop constraint historical_backfill_tasks_asset_type_check;

alter table market_data.historical_backfill_tasks
add constraint historical_backfill_tasks_asset_type_check check (
    asset_type in ('COMMON_STOCK', 'ETF', 'BENCHMARK')
) not valid;

alter table market_data.historical_backfill_tasks
validate constraint historical_backfill_tasks_asset_type_check;

alter table market_data.historical_backfill_tasks
drop constraint historical_backfill_task_identity_check;

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
        or (
            asset_type = 'BENCHMARK'
            and security_id is null
            and source_dataset = 'benchmark_total_return'
            and source_symbol = 'TAIEX'
            and market = 'TWSE'
        )
    )
) not valid;

alter table market_data.historical_backfill_tasks
validate constraint historical_backfill_task_identity_check;

alter table market_data.historical_backfill_tasks
drop constraint historical_backfill_task_research_scope_check;

alter table market_data.historical_backfill_tasks
add constraint historical_backfill_task_research_scope_check check (
    usage_scope = 'RAW_LANDING_ONLY'
    and system_status = 'RESEARCH_ONLY'
    and (
        (
            asset_type = 'BENCHMARK'
            and selection_basis = 'FIXED_BENCHMARK_REQUEST'
            and 'POINT_IN_TIME_UNVERIFIED' = any(reason_codes)
        )
        or (
            asset_type != 'BENCHMARK'
            and selection_basis = 'CURRENT_SECURITY_MASTER_SCHEDULING_ONLY'
            and 'REQUEST_UNIVERSE_NOT_POINT_IN_TIME' = any(reason_codes)
        )
        or (
            asset_type = 'COMMON_STOCK'
            and security_id is null
            and selection_basis = 'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
            and 'REQUEST_UNIVERSE_NOT_POINT_IN_TIME' = any(reason_codes)
            and 'IDENTITY_UNRESOLVED' = any(reason_codes)
            and 'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
            = any(reason_codes)
        )
    )
) not valid;

alter table market_data.historical_backfill_tasks
validate constraint historical_backfill_task_research_scope_check;

create or replace function market_data.seed_historical_benchmark_backfill_task(
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
    archived boolean;
begin
    if p_start_date is null
       or p_end_date is null
       or p_selection_snapshot_at is null
       or p_start_date > p_end_date then
        raise exception using
            errcode = '22023',
            message = 'valid benchmark start, end and snapshot are required';
    end if;

    select exists (
        select 1
        from market_data.historical_archive_objects as archive
        where archive.provider_code = 'FINMIND'
          and archive.source_dataset = 'benchmark_total_return'
          and archive.source_symbol = 'TAIEX'
          and archive.scheduled_market = 'TWSE'
          and archive.asset_type = 'BENCHMARK'
          and archive.requested_start_date <= p_start_date
          and archive.requested_end_date >= p_end_date
    ) into archived;

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
        status,
        latest_completed_trade_date,
        completed_at,
        last_result_code,
        reason_codes
    ) values (
        'FINMIND',
        'benchmark_total_return',
        null,
        'TAIEX',
        'TAIEX Total Return Index',
        'TWSE',
        'BENCHMARK',
        p_start_date,
        p_end_date,
        p_selection_snapshot_at,
        'FIXED_BENCHMARK_REQUEST',
        case when archived then 'SUCCEEDED' else 'PENDING' end,
        case when archived then p_end_date else null end,
        case when archived then now() else null end,
        case when archived then 'PREEXISTING_R2_ARCHIVE' else null end,
        array[
            'FIXED_BENCHMARK_REQUEST',
            'POINT_IN_TIME_UNVERIFIED',
            'HISTORICAL_VINTAGE_UNAVAILABLE',
            'RAW_LANDING_ONLY'
        ]
    )
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

create or replace function market_data.claim_historical_benchmark_backfill_task(
    p_provider_code text,
    p_worker_id text,
    p_claim_token uuid,
    p_lease_seconds integer default 1800
)
returns setof market_data.historical_backfill_tasks
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
begin
    if nullif(btrim(p_provider_code), '') is null
       or nullif(btrim(p_worker_id), '') is null
       or p_claim_token is null
       or p_lease_seconds is null
       or p_lease_seconds not between 60 and 3600 then
        raise exception using
            errcode = '22023',
            message = 'provider, worker, token and valid lease are required';
    end if;

    update market_data.historical_backfill_tasks as expired
    set
        status = 'EXHAUSTED',
        lease_token = null,
        claimed_by = null,
        lease_expires_at = null,
        completed_at = now(),
        last_error_code = 'LEASE_EXPIRED_AT_MAX_ATTEMPTS',
        updated_at = now()
    where expired.provider_code = p_provider_code
      and expired.source_dataset = 'benchmark_total_return'
      and expired.market = 'TWSE'
      and expired.asset_type = 'BENCHMARK'
      and expired.status = 'LEASED'
      and expired.lease_expires_at <= now()
      and expired.attempt_count >= expired.max_attempts;

    return query
    with candidate as materialized (
        select queued.task_id
        from market_data.historical_backfill_tasks as queued
        where queued.provider_code = p_provider_code
          and queued.source_dataset = 'benchmark_total_return'
          and queued.market = 'TWSE'
          and queued.asset_type = 'BENCHMARK'
          and queued.attempt_count < queued.max_attempts
          and (
              (
                  queued.status in ('PENDING', 'RETRY')
                  and queued.next_attempt_at <= now()
              )
              or (
                  queued.status = 'LEASED'
                  and queued.lease_expires_at <= now()
              )
          )
        order by queued.requested_start_date, queued.task_id
        for update of queued skip locked
        limit 1
    )
    update market_data.historical_backfill_tasks as task
    set
        status = 'LEASED',
        attempt_count = task.attempt_count + 1,
        lease_token = p_claim_token,
        claimed_by = p_worker_id,
        lease_expires_at = now() + make_interval(secs => p_lease_seconds),
        completed_at = null,
        updated_at = now()
    from candidate
    where task.task_id = candidate.task_id
    returning task.*;
end
$function$;

comment on function market_data.seed_historical_benchmark_backfill_task(
    date,
    date,
    timestamptz
) is 'Seeds exactly one research-only FinMind TAIEX total-return task.';

comment on function market_data.claim_historical_benchmark_backfill_task(
    text,
    text,
    uuid,
    integer
) is 'Claims only the isolated TAIEX benchmark task.';

revoke all on function market_data.seed_historical_benchmark_backfill_task(
    date,
    date,
    timestamptz
) from public, anon, authenticated;

revoke all on function market_data.claim_historical_benchmark_backfill_task(
    text,
    text,
    uuid,
    integer
) from public, anon, authenticated;

grant execute on function market_data.seed_historical_benchmark_backfill_task(
    date,
    date,
    timestamptz
) to service_role;

grant execute on function market_data.claim_historical_benchmark_backfill_task(
    text,
    text,
    uuid,
    integer
) to service_role;

notify pgrst, 'reload schema';

commit;
