-- Run after `supabase migration down --local --last 1`.
-- It proves the previous constraint rejects date-only open-session hints.
begin;

insert into market_data.data_sources (
    source_code,
    display_name,
    source_timezone,
    revision_policy,
    is_active
) values (
    'CALENDAR_ROLLBACK_TEST',
    'Calendar rollback test fixture',
    'Asia/Taipei',
    'TEST_ONLY',
    false
) on conflict (source_code) do nothing;

do $rollback_validation$
declare
    fixture_source_id bigint;
begin
    select source_id into strict fixture_source_id
    from market_data.data_sources
    where source_code = 'CALENDAR_ROLLBACK_TEST';

    begin
        insert into market_data.trading_calendar_observations (
            market, trading_date, is_trading_day, opens_at, closes_at,
            decision_data_cutoff_at, market_basis,
            calendar_verification_status, source_id, source_dataset,
            source_event_id, source_version, source_revision_hash,
            source_payload_hash, source_url, source_row, first_observed_at,
            available_at, available_at_basis, usage_scope, system_status,
            reason_codes
        ) values (
            'TWSE', date '2026-07-17', true, null, null, null,
            'SCHEDULING_HINT', 'UNRESOLVED', fixture_source_id,
            'TaiwanStockTradingDate', 'FINMIND:TWSE:2026-07-17',
            'api.v4+test', repeat('a', 64), repeat('b', 64),
            'https://api.finmindtrade.com/api/v4/data',
            '{"date":"2026-07-17"}'::jsonb,
            timestamptz '2026-07-18 00:00:00+00',
            timestamptz '2026-07-18 00:00:00+00',
            'FIRST_OBSERVED_AT_RETRIEVAL', 'CALENDAR_RESEARCH_ONLY',
            'RESEARCH_ONLY', array['OFFICIAL_SESSION_TIMES_UNAVAILABLE']
        );
        raise exception 'PREVIOUS_CONSTRAINT_ACCEPTED_DATE_ONLY_HINT';
    exception when check_violation then
        null;
    end;
end;
$rollback_validation$;

rollback;
