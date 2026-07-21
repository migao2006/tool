begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

alter table market_data.historical_archive_objects
add constraint historical_archive_scope_check_fugle check (
    storage_provider = 'CLOUDFLARE_R2'
    and (
        (
            provider_code = 'FINMIND'
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
                when 'institutional_flows'
                    then 'historical_institutional_flows.v1'
                when 'margin_short' then 'historical_margin_short.v1'
                when 'benchmark_total_return'
                    then 'historical_benchmark_total_return.v1'
            end
        )
        or (
            provider_code = 'TWSE'
            and source_dataset = 'taiex_price_index_ohlc'
            and schema_version = 'twse_taiex_price_index_ohlc.v1'
        )
        or (
            provider_code = 'FUGLE'
            and source_dataset = 'adjusted_bars'
            and schema_version = 'historical_adjusted_bars.v1'
        )
    )
    and scheduled_market in ('TWSE', 'TPEX')
    and (
        (
            provider_code = 'FUGLE'
            and source_dataset = 'adjusted_bars'
            and scheduled_market = 'TWSE'
            and asset_type = 'COMMON_STOCK'
            and source_symbol ~ '^[1-9][0-9]{3}$'
        )
        or (
            provider_code = 'TWSE'
            and source_dataset = 'taiex_price_index_ohlc'
            and scheduled_market = 'TWSE'
            and asset_type = 'BENCHMARK'
            and source_symbol = 'TAIEX'
        )
        or (
            provider_code = 'FINMIND'
            and source_dataset = 'benchmark_total_return'
            and scheduled_market = 'TWSE'
            and asset_type = 'BENCHMARK'
            and source_symbol = 'TAIEX'
        )
        or (
            provider_code = 'FINMIND'
            and source_dataset != 'benchmark_total_return'
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
validate constraint historical_archive_scope_check_fugle;

alter table market_data.historical_archive_objects
drop constraint historical_archive_scope_check;

alter table market_data.historical_archive_objects
rename constraint historical_archive_scope_check_fugle
to historical_archive_scope_check;

-- noqa: disable=PG01
create index if not exists historical_backfill_fugle_adjusted_claim_idx
on market_data.historical_backfill_tasks (
    status,
    next_attempt_at,
    requested_start_date,
    source_symbol,
    task_id
)
where provider_code = 'FUGLE'
and source_dataset = 'adjusted_bars'
and market = 'TWSE'
and asset_type = 'COMMON_STOCK';
-- noqa: enable=PG01

create or replace function
market_data.seed_historical_fugle_adjusted_twse_tasks(
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
            message = 'valid Fugle start, end and selection snapshot are required';
    end if;

    with candidates as materialized (
        select
            security.security_id,
            security.symbol,
            security.display_name,
            greatest(
                p_start_date,
                coalesce(security.listing_date, p_start_date)
            ) as range_start,
            least(
                p_end_date,
                coalesce(security.delisting_date, p_end_date)
            ) as range_end
        from market_data.securities as security
        where security.market = 'TWSE'
          and security.asset_type = 'COMMON_STOCK'
          and security.symbol ~ '^[1-9][0-9]{3}$'
    ), chunks as materialized (
        select
            candidate.security_id,
            candidate.symbol,
            candidate.display_name,
            chunk_start::date as range_start,
            least(
                chunk_start::date + 365,
                candidate.range_end
            ) as range_end
        from candidates as candidate
        cross join lateral generate_series(
            candidate.range_start::timestamp,
            candidate.range_end::timestamp,
            interval '366 days'
        ) as series(chunk_start)
        where candidate.range_start <= candidate.range_end
    ), coverage as materialized (
        select
            chunk.*,
            exists (
                select 1
                from market_data.historical_archive_objects as archive
                where archive.provider_code = 'FUGLE'
                  and archive.source_dataset = 'adjusted_bars'
                  and archive.source_symbol = chunk.symbol
                  and archive.scheduled_market = 'TWSE'
                  and archive.asset_type = 'COMMON_STOCK'
                  and archive.requested_start_date <= chunk.range_start
                  and archive.requested_end_date >= chunk.range_end
            ) as already_archived
        from chunks as chunk
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
        last_result_code,
        reason_codes
    )
    select
        'FUGLE',
        'adjusted_bars',
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
        case
            when coverage.already_archived then 'PREEXISTING_R2_ARCHIVE'
            else null
        end,
        array[
            'FUGLE_ADJUSTED_BACKFILL',
            'REQUEST_UNIVERSE_NOT_POINT_IN_TIME',
            'HISTORICAL_VINTAGE_UNAVAILABLE',
            'IDENTITY_UNRESOLVED',
            'RAW_LANDING_ONLY'
        ]
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

create or replace function
market_data.claim_historical_fugle_adjusted_backfill_task(
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
    if nullif(btrim(p_worker_id), '') is null
       or p_claim_token is null
       or p_lease_seconds is null
       or p_lease_seconds not between 60 and 3600 then
        raise exception using
            errcode = '22023',
            message = 'worker, token and valid lease are required';
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
    where expired.provider_code = 'FUGLE'
      and expired.source_dataset = 'adjusted_bars'
      and expired.market = 'TWSE'
      and expired.asset_type = 'COMMON_STOCK'
      and expired.status = 'LEASED'
      and expired.lease_expires_at <= now()
      and expired.attempt_count >= expired.max_attempts;

    return query
    with candidate as materialized (
        select queued.task_id
        from market_data.historical_backfill_tasks as queued
        where queued.provider_code = 'FUGLE'
          and queued.source_dataset = 'adjusted_bars'
          and queued.market = 'TWSE'
          and queued.asset_type = 'COMMON_STOCK'
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
        order by
            queued.requested_start_date,
            queued.source_symbol,
            queued.task_id
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

create or replace function
market_data.historical_fugle_adjusted_backfill_snapshot(
    p_start_date date,
    p_end_date date
)
returns table (
    task_count bigint,
    remaining bigint,
    succeeded bigint,
    exhausted bigint,
    archive_object_count bigint,
    archive_row_count bigint,
    archive_byte_count bigint
)
language sql
stable
security invoker
set search_path = pg_catalog, market_data
as $function$
    with task_summary as materialized (
        select
            count(*) as task_count,
            count(*) filter (
                where task.status in ('PENDING', 'LEASED', 'RETRY')
            ) as remaining,
            count(*) filter (where task.status = 'SUCCEEDED') as succeeded,
            count(*) filter (where task.status = 'EXHAUSTED') as exhausted
        from market_data.historical_backfill_tasks as task
        where task.provider_code = 'FUGLE'
          and task.source_dataset = 'adjusted_bars'
          and task.market = 'TWSE'
          and task.asset_type = 'COMMON_STOCK'
          and task.requested_start_date >= p_start_date
          and task.requested_end_date <= p_end_date
    ), archive_summary as materialized (
        select
            count(*) as archive_object_count,
            coalesce(sum(archive.row_count), 0)::bigint as archive_row_count,
            coalesce(sum(archive.byte_size), 0)::bigint as archive_byte_count
        from market_data.historical_archive_objects as archive
        where archive.provider_code = 'FUGLE'
          and archive.source_dataset = 'adjusted_bars'
          and archive.scheduled_market = 'TWSE'
          and archive.asset_type = 'COMMON_STOCK'
          and archive.requested_start_date >= p_start_date
          and archive.requested_end_date <= p_end_date
    )
    select
        task_summary.task_count,
        task_summary.remaining,
        task_summary.succeeded,
        task_summary.exhausted,
        archive_summary.archive_object_count,
        archive_summary.archive_row_count,
        archive_summary.archive_byte_count
    from task_summary
    cross join archive_summary;
$function$;

comment on function market_data.seed_historical_fugle_adjusted_twse_tasks(
    date,
    date,
    timestamptz
) is 'Seeds isolated Fugle adjusted tasks in at most 366-day chunks.';

comment on function market_data.claim_historical_fugle_adjusted_backfill_task(
    text,
    uuid,
    integer
) is 'Claims only isolated FUGLE adjusted_bars tasks.';

comment on function market_data.historical_fugle_adjusted_backfill_snapshot(
    date,
    date
) is 'Summarizes only FUGLE adjusted_bars queue and R2 manifests.';

revoke all on function market_data.seed_historical_fugle_adjusted_twse_tasks(
    date,
    date,
    timestamptz
) from public, anon, authenticated;

revoke all on function
market_data.claim_historical_fugle_adjusted_backfill_task(
    text,
    uuid,
    integer
) from public, anon, authenticated;

revoke all on function market_data.historical_fugle_adjusted_backfill_snapshot(
    date,
    date
) from public, anon, authenticated;

grant execute on function market_data.seed_historical_fugle_adjusted_twse_tasks(
    date,
    date,
    timestamptz
) to service_role;

grant execute on function
market_data.claim_historical_fugle_adjusted_backfill_task(
    text,
    uuid,
    integer
) to service_role;

grant execute on function
market_data.historical_fugle_adjusted_backfill_snapshot(
    date,
    date
) to service_role;

notify pgrst, 'reload schema';

commit;
