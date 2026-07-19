-- Representative Staging validation for isolated supplemental and benchmark
-- queues.
-- Requires at least one real TWSE COMMON_STOCK security and always rolls back.
begin;

do $validation$
declare
    seeded_supplemental integer;
    supplemental_tasks integer;
    supplemental_claims integer;
    seeded_benchmark integer;
    benchmark_claims integer;
begin
    select market_data.seed_historical_supplemental_twse_tasks(
        date '2021-07-19',
        date '2026-07-17',
        statement_timestamp()
    ) into seeded_supplemental;

    select count(*) into supplemental_tasks
    from market_data.historical_backfill_tasks
    where source_dataset in (
        'adjusted_bars', 'institutional_flows', 'margin_short'
    )
      and market = 'TWSE'
      and asset_type = 'COMMON_STOCK';

    if seeded_supplemental <> 3 or supplemental_tasks <> 3 then
        raise exception 'SUPPLEMENTAL_SEED_CONTRACT_FAILED';
    end if;

    select count(*) into supplemental_claims
    from market_data.claim_historical_supplemental_backfill_task(
        'FINMIND',
        'staging-validation',
        '00000000-0000-4000-8000-000000000001'::uuid,
        60
    );

    if supplemental_claims <> 1 then
        raise exception 'SUPPLEMENTAL_CLAIM_CONTRACT_FAILED';
    end if;

    select market_data.seed_historical_benchmark_backfill_task(
        date '2021-07-19',
        date '2026-07-17',
        statement_timestamp()
    ) into seeded_benchmark;

    select count(*) into benchmark_claims
    from market_data.claim_historical_benchmark_backfill_task(
        'FINMIND',
        'staging-validation',
        '00000000-0000-4000-8000-000000000002'::uuid,
        60
    );

    if seeded_benchmark <> 1 or benchmark_claims <> 1 then
        raise exception 'BENCHMARK_QUEUE_CONTRACT_FAILED';
    end if;

    if (
        select count(*)
        from market_data.historical_backfill_tasks
        where source_dataset = 'daily_bars'
    ) <> 2 then
        raise exception 'EXISTING_DAILY_TASKS_CHANGED';
    end if;
end;
$validation$;

rollback;
