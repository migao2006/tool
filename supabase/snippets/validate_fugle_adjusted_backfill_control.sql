begin;

set local search_path = pg_catalog, public, extensions;

do $validation$
declare
    seeded integer;
    max_inclusive_days integer;
    wrong_scope_count integer;
begin
    insert into market_data.data_sources (
        source_code,
        display_name,
        source_timezone,
        revision_policy,
        is_active
    ) values (
        'FUGLE',
        'Fugle MarketData v1',
        'Asia/Taipei',
        'PAYLOAD_HASH_VERSIONED_RETRIEVED_AT_LOWER_BOUND',
        true
    ) on conflict (source_code) do nothing;

    insert into market_data.securities (
        symbol,
        display_name,
        market,
        asset_type,
        listing_date,
        source_id
    )
    select
        '2330',
        'Local Fugle Contract Fixture',
        'TWSE',
        'COMMON_STOCK',
        date '1994-09-05',
        source.source_id
    from market_data.data_sources as source
    where source.source_code = 'FUGLE'
    on conflict (market, symbol) do nothing;

    seeded := market_data.seed_historical_fugle_adjusted_twse_tasks(
        date '2024-01-01',
        date '2026-01-01',
        now()
    );

    if seeded < 1 then
        raise exception 'Fugle validation expected at least one seeded task';
    end if;

    select max(requested_end_date - requested_start_date + 1)
    into max_inclusive_days
    from market_data.historical_backfill_tasks
    where provider_code = 'FUGLE'
      and source_dataset = 'adjusted_bars';

    if max_inclusive_days > 366 then
        raise exception 'Fugle task exceeded 366 inclusive days';
    end if;

    select count(*)
    into wrong_scope_count
    from market_data.historical_backfill_tasks
    where provider_code = 'FUGLE'
      and (
          source_dataset != 'adjusted_bars'
          or market != 'TWSE'
          or asset_type != 'COMMON_STOCK'
      );

    if wrong_scope_count != 0 then
        raise exception 'Fugle task escaped its provider scope';
    end if;
end
$validation$;

rollback;
