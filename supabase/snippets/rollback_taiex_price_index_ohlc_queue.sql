begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

do $guard$
begin
    if exists (
        select 1
        from pg_catalog.pg_proc as procedure
        join pg_catalog.pg_namespace as namespace
          on namespace.oid = procedure.pronamespace
        where namespace.nspname = 'market_data'
          and procedure.proname
          = 'seed_historical_fugle_adjusted_twse_tasks'
    ) then
        raise exception using
            errcode = '55000',
            message = 'rollback blocked: rollback newer Fugle migration first';
    end if;

    if exists (
        select 1
        from market_data.historical_backfill_tasks
        where provider_code = 'TWSE'
          and source_dataset = 'taiex_price_index_ohlc'
    ) or exists (
        select 1
        from market_data.historical_archive_objects
        where provider_code = 'TWSE'
          and source_dataset = 'taiex_price_index_ohlc'
    ) then
        raise exception using
            errcode = '55000',
            message = 'rollback blocked: TAIEX OHLC queue or archive records exist';
    end if;
end
$guard$;

drop function if exists market_data.seed_taiex_price_index_ohlc_tasks(
    date,
    date,
    timestamptz
);
drop function if exists market_data.claim_taiex_price_index_ohlc_task(
    text,
    uuid,
    integer
);
drop function if exists market_data.complete_taiex_price_index_ohlc_task(
    bigint,
    uuid,
    boolean,
    date,
    integer,
    integer,
    integer,
    text
);
drop function if exists market_data.taiex_price_index_ohlc_backfill_snapshot(
    date,
    date
);

-- noqa: disable=PG01
drop index if exists
market_data.historical_backfill_tasks_taiex_month_claim_idx;
-- noqa: enable=PG01

alter table market_data.historical_archive_objects
add constraint historical_archive_scope_check_rollback check (
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
validate constraint historical_archive_scope_check_rollback;
alter table market_data.historical_archive_objects
drop constraint historical_archive_scope_check;
alter table market_data.historical_archive_objects
rename constraint historical_archive_scope_check_rollback
to historical_archive_scope_check;

alter table market_data.historical_backfill_tasks
add constraint historical_backfill_task_identity_check_rollback check (
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
validate constraint historical_backfill_task_identity_check_rollback;
alter table market_data.historical_backfill_tasks
drop constraint historical_backfill_task_identity_check;
alter table market_data.historical_backfill_tasks
rename constraint historical_backfill_task_identity_check_rollback
to historical_backfill_task_identity_check;

alter table market_data.historical_backfill_tasks
add constraint historical_backfill_task_research_scope_check_rollback check (
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
validate constraint historical_backfill_task_research_scope_check_rollback;
alter table market_data.historical_backfill_tasks
drop constraint historical_backfill_task_research_scope_check;
alter table market_data.historical_backfill_tasks
rename constraint historical_backfill_task_research_scope_check_rollback
to historical_backfill_task_research_scope_check;

notify pgrst, 'reload schema';

commit;
