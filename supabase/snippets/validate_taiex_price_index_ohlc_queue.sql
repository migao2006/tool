begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

insert into market_data.data_sources (
    source_code,
    display_name,
    source_timezone,
    revision_policy,
    is_active
) values
(
    'TWSE',
    'Taiwan Stock Exchange',
    'Asia/Taipei',
    'PAYLOAD_HASH_VERSIONED',
    true
),
('FINMIND', 'FinMind', 'Asia/Taipei', 'PAYLOAD_HASH_VERSIONED', true)
on conflict (source_code) do nothing;

do $validation$
declare
    inserted_count integer;
    claimed market_data.historical_backfill_tasks%rowtype;
    snapshot record;
    current_month date;
begin
    select market_data.seed_taiex_price_index_ohlc_tasks(
        date '2024-01-01',
        date '2024-03-01',
        timestamptz '2026-07-19 00:00:00+00'
    ) into inserted_count;
    if inserted_count != 3 then
        raise exception 'expected three monthly tasks, got %', inserted_count;
    end if;

    select market_data.seed_taiex_price_index_ohlc_tasks(
        date '2024-01-01',
        date '2024-03-01',
        timestamptz '2026-07-19 00:00:00+00'
    ) into inserted_count;
    if inserted_count != 0 then
        raise exception 'monthly seed is not idempotent';
    end if;

    if exists (
        select 1
        from market_data.historical_backfill_tasks
        where provider_code = 'TWSE'
          and source_dataset = 'taiex_price_index_ohlc'
          and (
              source_symbol != 'TAIEX'
              or market != 'TWSE'
              or asset_type != 'BENCHMARK'
              or selection_basis != 'FIXED_TAIEX_MONTH_REQUEST'
              or requested_start_date
                  != date_trunc('month', requested_start_date)::date
              or requested_end_date
                  != (
                      requested_start_date + interval '1 month - 1 day'
                  )::date
              or usage_scope != 'RAW_LANDING_ONLY'
              or system_status != 'RESEARCH_ONLY'
              or not ('PRICE_INDEX_NOT_TOTAL_RETURN' = any(reason_codes))
          )
    ) then
        raise exception 'seeded task escaped the fixed research-only scope';
    end if;

    select * into claimed
    from market_data.claim_taiex_price_index_ohlc_task(
        'local-validation',
        '11111111-1111-4111-8111-111111111111'::uuid,
        600
    );
    if claimed.task_id is null
       or claimed.requested_start_date != date '2024-01-01' then
        raise exception 'oldest monthly task was not claimed';
    end if;

    if not market_data.complete_taiex_price_index_ohlc_task(
        claimed.task_id,
        '11111111-1111-4111-8111-111111111111'::uuid,
        false,
        null,
        0,
        0,
        900,
        'LOCAL_VALIDATION_RETRY'
    ) then
        raise exception 'isolated monthly task completion was rejected';
    end if;

    select * into snapshot
    from market_data.taiex_price_index_ohlc_backfill_snapshot(
        date '2024-01-01',
        date '2024-03-01'
    );
    if snapshot.task_count != 3
       or snapshot.pending != 2
       or snapshot.retry != 1
       or snapshot.exhausted != 0 then
        raise exception 'unexpected monthly queue snapshot: %', row_to_json(snapshot);
    end if;

    current_month := date_trunc(
        'month',
        now() at time zone 'Asia/Taipei'
    )::date;
    begin
        perform market_data.seed_taiex_price_index_ohlc_tasks(
            current_month,
            current_month,
            now()
        );
        raise exception 'current month was incorrectly accepted';
    exception
        when invalid_parameter_value then null;
    end;

    begin
        insert into market_data.historical_backfill_tasks (
            provider_code,
            source_dataset,
            source_symbol,
            display_name,
            market,
            asset_type,
            requested_start_date,
            requested_end_date,
            selection_snapshot_at,
            selection_basis,
            reason_codes
        ) values (
            'FINMIND',
            'taiex_price_index_ohlc',
            'TAIEX',
            'Invalid cross-provider task',
            'TWSE',
            'BENCHMARK',
            date '2020-01-01',
            date '2020-01-31',
            now(),
            'FIXED_TAIEX_MONTH_REQUEST',
            array[
                'POINT_IN_TIME_UNVERIFIED',
                'AVAILABLE_AT_FIRST_RETRIEVAL_ONLY',
                'PRICE_INDEX_NOT_TOTAL_RETURN',
                'RAW_LANDING_ONLY'
            ]
        );
        raise exception 'cross-provider dataset combination was incorrectly accepted';
    exception
        when check_violation then null;
    end;
end
$validation$;

rollback;
