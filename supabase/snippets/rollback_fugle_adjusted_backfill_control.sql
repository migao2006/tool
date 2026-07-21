begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

do $guard$
begin
    if exists (
        select 1
        from market_data.historical_backfill_tasks
        where provider_code = 'FUGLE'
          and source_dataset = 'adjusted_bars'
    ) or exists (
        select 1
        from market_data.historical_archive_objects
        where provider_code = 'FUGLE'
          and source_dataset = 'adjusted_bars'
    ) then
        raise exception using
            errcode = '55000',
            message = 'rollback blocked: Fugle tasks or archive records exist';
    end if;
end
$guard$;

drop function if exists
market_data.historical_fugle_adjusted_backfill_snapshot(date, date);
drop function if exists
market_data.claim_historical_fugle_adjusted_backfill_task(text, uuid, integer);
drop function if exists
market_data.seed_historical_fugle_adjusted_twse_tasks(
    date,
    date,
    timestamptz
);

-- noqa: disable=PG01
drop index if exists market_data.historical_backfill_fugle_adjusted_claim_idx;
-- noqa: enable=PG01

alter table market_data.historical_archive_objects
add constraint historical_archive_scope_check_rollback check (
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
validate constraint historical_archive_scope_check_rollback;

alter table market_data.historical_archive_objects
drop constraint historical_archive_scope_check;

alter table market_data.historical_archive_objects
rename constraint historical_archive_scope_check_rollback
to historical_archive_scope_check;

notify pgrst, 'reload schema';

commit;
