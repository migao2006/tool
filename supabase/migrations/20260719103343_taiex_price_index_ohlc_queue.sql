begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

alter table market_data.historical_archive_objects
add constraint historical_archive_scope_check_v2 check (
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
        )
        or (
            provider_code = 'TWSE'
            and source_dataset = 'taiex_price_index_ohlc'
            and schema_version = 'twse_taiex_price_index_ohlc.v1'
            and scheduled_market = 'TWSE'
            and asset_type = 'BENCHMARK'
            and source_symbol = 'TAIEX'
        )
        or (
            provider_code = 'FUGLE'
            and source_dataset = 'adjusted_bars'
            and schema_version = 'historical_adjusted_bars.v1'
            and scheduled_market = 'TWSE'
            and asset_type = 'COMMON_STOCK'
            and source_symbol ~ '^[1-9][0-9]{3}$'
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
validate constraint historical_archive_scope_check_v2;

alter table market_data.historical_archive_objects
drop constraint historical_archive_scope_check;

alter table market_data.historical_archive_objects
rename constraint historical_archive_scope_check_v2
to historical_archive_scope_check;

alter table market_data.historical_backfill_tasks
add constraint historical_backfill_task_identity_check_v2 check (
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
            and source_symbol = 'TAIEX'
            and market = 'TWSE'
            and (
                (
                    provider_code = 'FINMIND'
                    and source_dataset = 'benchmark_total_return'
                    and selection_basis = 'FIXED_BENCHMARK_REQUEST'
                )
                or (
                    provider_code = 'TWSE'
                    and source_dataset = 'taiex_price_index_ohlc'
                    and selection_basis = 'FIXED_TAIEX_MONTH_REQUEST'
                    and requested_start_date
                    = date_trunc('month', requested_start_date)::date
                    and requested_end_date
                    = (
                        requested_start_date
                        + interval '1 month - 1 day'
                    )::date
                )
            )
        )
    )
) not valid;

alter table market_data.historical_backfill_tasks
validate constraint historical_backfill_task_identity_check_v2;

alter table market_data.historical_backfill_tasks
drop constraint historical_backfill_task_identity_check;

alter table market_data.historical_backfill_tasks
rename constraint historical_backfill_task_identity_check_v2
to historical_backfill_task_identity_check;

alter table market_data.historical_backfill_tasks
add constraint historical_backfill_task_research_scope_check_v2 check (
    usage_scope = 'RAW_LANDING_ONLY'
    and system_status = 'RESEARCH_ONLY'
    and (
        (
            asset_type = 'BENCHMARK'
            and 'POINT_IN_TIME_UNVERIFIED' = any(reason_codes)
            and (
                (
                    provider_code = 'FINMIND'
                    and source_dataset = 'benchmark_total_return'
                    and selection_basis = 'FIXED_BENCHMARK_REQUEST'
                )
                or (
                    provider_code = 'TWSE'
                    and source_dataset = 'taiex_price_index_ohlc'
                    and selection_basis = 'FIXED_TAIEX_MONTH_REQUEST'
                    and 'PRICE_INDEX_NOT_TOTAL_RETURN' = any(reason_codes)
                    and 'AVAILABLE_AT_FIRST_RETRIEVAL_ONLY' = any(reason_codes)
                )
            )
        )
        or (
            asset_type != 'BENCHMARK'
            and selection_basis = 'CURRENT_SECURITY_MASTER_SCHEDULING_ONLY'
            and 'REQUEST_UNIVERSE_NOT_POINT_IN_TIME' = any(reason_codes)
        )
        or (
            asset_type = 'COMMON_STOCK'
            and security_id is null
            and selection_basis
            = 'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
            and 'REQUEST_UNIVERSE_NOT_POINT_IN_TIME' = any(reason_codes)
            and 'IDENTITY_UNRESOLVED' = any(reason_codes)
            and 'OFFICIAL_DELISTING_REGISTRY_SCHEDULING_ONLY'
            = any(reason_codes)
        )
    )
) not valid;

alter table market_data.historical_backfill_tasks
validate constraint historical_backfill_task_research_scope_check_v2;

alter table market_data.historical_backfill_tasks
drop constraint historical_backfill_task_research_scope_check;

alter table market_data.historical_backfill_tasks
rename constraint historical_backfill_task_research_scope_check_v2
to historical_backfill_task_research_scope_check;

-- noqa: disable=PG01
create index if not exists historical_backfill_tasks_taiex_month_claim_idx
on market_data.historical_backfill_tasks (
    status,
    next_attempt_at,
    requested_start_date,
    task_id
)
where provider_code = 'TWSE'
and source_dataset = 'taiex_price_index_ohlc'
and source_symbol = 'TAIEX'
and market = 'TWSE'
and asset_type = 'BENCHMARK'
and status in ('PENDING', 'RETRY', 'LEASED');
-- noqa: enable=PG01

create or replace function market_data.seed_taiex_price_index_ohlc_tasks(
    p_start_month date,
    p_end_month date,
    p_selection_snapshot_at timestamptz
)
returns integer
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
declare
    inserted_count integer;
    current_taipei_month date;
begin
    if p_start_month is null
       or p_end_month is null
       or p_selection_snapshot_at is null
       or p_start_month > p_end_month
       or p_start_month != date_trunc('month', p_start_month)::date
       or p_end_month != date_trunc('month', p_end_month)::date then
        raise exception using
            errcode = '22023',
            message = 'valid Gregorian first-of-month bounds are required';
    end if;

    current_taipei_month := date_trunc(
        'month',
        p_selection_snapshot_at at time zone 'Asia/Taipei'
    )::date;
    if p_end_month >= current_taipei_month then
        raise exception using
            errcode = '22023',
            message = 'TAIEX OHLC queue accepts completed calendar months only';
    end if;

    with months as materialized (
        select month_start::date as month_start
        from generate_series(
            p_start_month::timestamp,
            p_end_month::timestamp,
            interval '1 month'
        ) as month_start
    ), month_ranges as materialized (
        select
            months.month_start,
            (months.month_start + interval '1 month - 1 day')::date
                as month_end
        from months
    ), archive_state as materialized (
        select
            month_ranges.month_start,
            month_ranges.month_end,
            archived.max_trade_date
        from month_ranges
        left join lateral (
            select max(archive.max_trade_date) as max_trade_date
            from market_data.historical_archive_objects as archive
            where archive.provider_code = 'TWSE'
              and archive.source_dataset = 'taiex_price_index_ohlc'
              and archive.source_symbol = 'TAIEX'
              and archive.scheduled_market = 'TWSE'
              and archive.asset_type = 'BENCHMARK'
              and archive.requested_start_date = month_ranges.month_start
              and archive.requested_end_date = month_ranges.month_end
        ) as archived on true
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
        status,
        latest_completed_trade_date,
        completed_at,
        last_result_code,
        reason_codes
    )
    select
        'TWSE',
        'taiex_price_index_ohlc',
        null,
        'TAIEX',
        'TAIEX Price Index OHLC',
        'TWSE',
        'BENCHMARK',
        archive_state.month_start,
        archive_state.month_end,
        p_selection_snapshot_at,
        'FIXED_TAIEX_MONTH_REQUEST',
        case
            when archive_state.max_trade_date is not null then 'SUCCEEDED'
            else 'PENDING'
        end,
        archive_state.max_trade_date,
        case
            when archive_state.max_trade_date is not null then now()
            else null
        end,
        case
            when archive_state.max_trade_date is not null
                then 'PREEXISTING_R2_ARCHIVE'
            else null
        end,
        array[
            'FIXED_TAIEX_MONTH_REQUEST',
            'POINT_IN_TIME_UNVERIFIED',
            'AVAILABLE_AT_FIRST_RETRIEVAL_ONLY',
            'HISTORICAL_VINTAGE_UNAVAILABLE',
            'PRICE_INDEX_NOT_TOTAL_RETURN',
            'RAW_LANDING_ONLY'
        ]
    from archive_state
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

create or replace function market_data.claim_taiex_price_index_ohlc_task(
    p_worker_id text,
    p_claim_token uuid,
    p_lease_seconds integer default 900
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
       or p_lease_seconds not between 60 and 1800 then
        raise exception using
            errcode = '22023',
            message = 'worker, claim token and a valid lease are required';
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
    where expired.provider_code = 'TWSE'
      and expired.source_dataset = 'taiex_price_index_ohlc'
      and expired.source_symbol = 'TAIEX'
      and expired.market = 'TWSE'
      and expired.asset_type = 'BENCHMARK'
      and expired.status = 'LEASED'
      and expired.lease_expires_at <= now()
      and expired.attempt_count >= expired.max_attempts;

    return query
    with candidate as materialized (
        select queued.task_id
        from market_data.historical_backfill_tasks as queued
        where queued.provider_code = 'TWSE'
          and queued.source_dataset = 'taiex_price_index_ohlc'
          and queued.source_symbol = 'TAIEX'
          and queued.market = 'TWSE'
          and queued.asset_type = 'BENCHMARK'
          and queued.selection_basis = 'FIXED_TAIEX_MONTH_REQUEST'
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

create or replace function market_data.complete_taiex_price_index_ohlc_task(
    p_task_id bigint,
    p_claim_token uuid,
    p_success boolean,
    p_latest_completed_trade_date date default null,
    p_fetched_rows integer default 0,
    p_archived_rows integer default 0,
    p_retry_after_seconds integer default 900,
    p_error_code text default null
)
returns boolean
language plpgsql
security invoker
set search_path = pg_catalog, market_data
as $function$
begin
    if not exists (
        select 1
        from market_data.historical_backfill_tasks as task
        where task.task_id = p_task_id
          and task.provider_code = 'TWSE'
          and task.source_dataset = 'taiex_price_index_ohlc'
          and task.source_symbol = 'TAIEX'
          and task.market = 'TWSE'
          and task.asset_type = 'BENCHMARK'
          and task.selection_basis = 'FIXED_TAIEX_MONTH_REQUEST'
    ) then
        return false;
    end if;

    return market_data.complete_historical_backfill_task(
        p_task_id,
        p_claim_token,
        p_success,
        p_latest_completed_trade_date,
        p_fetched_rows,
        p_archived_rows,
        0,
        0,
        p_retry_after_seconds,
        p_error_code
    );
end
$function$;

create or replace function market_data.taiex_price_index_ohlc_backfill_snapshot(
    p_start_month date,
    p_end_month date
)
returns table (
    task_count bigint,
    pending bigint,
    leased bigint,
    retry bigint,
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
    with task_counts as (
        select
            count(*) as task_count,
            count(*) filter (where status = 'PENDING') as pending,
            count(*) filter (where status = 'LEASED') as leased,
            count(*) filter (where status = 'RETRY') as retry,
            count(*) filter (where status = 'SUCCEEDED') as succeeded,
            count(*) filter (where status = 'EXHAUSTED') as exhausted
        from market_data.historical_backfill_tasks
        where provider_code = 'TWSE'
          and source_dataset = 'taiex_price_index_ohlc'
          and source_symbol = 'TAIEX'
          and market = 'TWSE'
          and asset_type = 'BENCHMARK'
          and requested_start_date between p_start_month and p_end_month
    ), archive_counts as (
        select
            count(*) as archive_object_count,
            coalesce(sum(row_count), 0)::bigint as archive_row_count,
            coalesce(sum(byte_size), 0)::bigint as archive_byte_count
        from market_data.historical_archive_objects
        where provider_code = 'TWSE'
          and source_dataset = 'taiex_price_index_ohlc'
          and source_symbol = 'TAIEX'
          and scheduled_market = 'TWSE'
          and asset_type = 'BENCHMARK'
          and requested_start_date between p_start_month and p_end_month
    )
    select
        task_counts.task_count,
        task_counts.pending,
        task_counts.leased,
        task_counts.retry,
        task_counts.succeeded,
        task_counts.exhausted,
        archive_counts.archive_object_count,
        archive_counts.archive_row_count,
        archive_counts.archive_byte_count
    from task_counts
    cross join archive_counts;
$function$;

comment on function market_data.seed_taiex_price_index_ohlc_tasks(
    date,
    date,
    timestamptz
) is
'Seeds completed Gregorian months for official TWSE TAIEX price-index OHLC.';

comment on function market_data.claim_taiex_price_index_ohlc_task(
    text,
    uuid,
    integer
) is 'Claims one isolated official TWSE TAIEX monthly OHLC task.';

comment on function market_data.complete_taiex_price_index_ohlc_task(
    bigint,
    uuid,
    boolean,
    date,
    integer,
    integer,
    integer,
    text
) is 'Completes only an isolated official TWSE TAIEX monthly OHLC task.';

revoke all on function market_data.seed_taiex_price_index_ohlc_tasks(
    date,
    date,
    timestamptz
) from public, anon, authenticated;

revoke all on function market_data.claim_taiex_price_index_ohlc_task(
    text,
    uuid,
    integer
) from public, anon, authenticated;

revoke all on function market_data.complete_taiex_price_index_ohlc_task(
    bigint,
    uuid,
    boolean,
    date,
    integer,
    integer,
    integer,
    text
) from public, anon, authenticated;

revoke all on function market_data.taiex_price_index_ohlc_backfill_snapshot(
    date,
    date
) from public, anon, authenticated;

grant execute on function market_data.seed_taiex_price_index_ohlc_tasks(
    date,
    date,
    timestamptz
) to service_role;

grant execute on function market_data.claim_taiex_price_index_ohlc_task(
    text,
    uuid,
    integer
) to service_role;

grant execute on function market_data.complete_taiex_price_index_ohlc_task(
    bigint,
    uuid,
    boolean,
    date,
    integer,
    integer,
    integer,
    text
) to service_role;

grant execute on function market_data.taiex_price_index_ohlc_backfill_snapshot(
    date,
    date
) to service_role;

notify pgrst, 'reload schema';

commit;
