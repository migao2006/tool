-- Local/Staging representative-data validation for migration 20260719065502.
-- The transaction is always rolled back and must never be used to seed
-- Production.
begin;

insert into market_data.data_sources (
    source_code,
    display_name,
    source_timezone,
    revision_policy,
    is_active
) values (
    'CALENDAR_MIGRATION_TEST',
    'Calendar migration test fixture',
    'Asia/Taipei',
    'TEST_ONLY',
    false
) on conflict (source_code) do nothing;

insert into market_data.trading_calendar_observations (
    market,
    trading_date,
    is_trading_day,
    opens_at,
    closes_at,
    decision_data_cutoff_at,
    market_basis,
    calendar_verification_status,
    source_id,
    source_dataset,
    source_event_id,
    source_version,
    source_revision_hash,
    source_payload_hash,
    source_url,
    source_row,
    first_observed_at,
    available_at,
    available_at_basis,
    usage_scope,
    system_status,
    reason_codes
) values (
    'TWSE',
    date '2026-07-17',
    true,
    null,
    null,
    null,
    'SCHEDULING_HINT',
    'UNRESOLVED',
    (
        select source_id
        from market_data.data_sources
        where source_code = 'CALENDAR_MIGRATION_TEST'
    ),
    'TaiwanStockTradingDate',
    'FINMIND:TWSE:2026-07-17',
    'api.v4+test',
    repeat('a', 64),
    repeat('b', 64),
    'https://api.finmindtrade.com/api/v4/data',
    '{"date":"2026-07-17"}'::jsonb,
    timestamptz '2026-07-18 00:00:00+00',
    timestamptz '2026-07-18 00:00:00+00',
    'FIRST_OBSERVED_AT_RETRIEVAL',
    'CALENDAR_RESEARCH_ONLY',
    'RESEARCH_ONLY',
    array['OFFICIAL_SESSION_TIMES_UNAVAILABLE']
);

do $validation$
declare
    fixture_source_id bigint;
begin
    select source_id into strict fixture_source_id
    from market_data.data_sources
    where source_code = 'CALENDAR_MIGRATION_TEST';

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
            'TWSE', date '2026-07-20', true, null, null, null,
            'SOURCE_ASSERTED', 'VERIFIED', fixture_source_id,
            'TEST', 'VERIFIED_WITHOUT_TIMES', 'test', repeat('c', 64),
            repeat('d', 64), 'https://example.com/calendar', '{}'::jsonb,
            timestamptz '2026-07-19 00:00:00+00',
            timestamptz '2026-07-19 00:00:00+00', 'VERSIONED_SNAPSHOT',
            'POINT_IN_TIME_CALENDAR', 'PASS', '{}'::text[]
        );
        raise exception 'VERIFIED_WITHOUT_TIMES_WAS_ACCEPTED';
    exception when check_violation then
        null;
    end;

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
            'TWSE', date '2026-07-20', true,
            timestamptz '2026-07-20 09:00:00+08', null, null,
            'SCHEDULING_HINT', 'UNRESOLVED', fixture_source_id,
            'TEST', 'PARTIAL_TIMESTAMPS', 'test', repeat('e', 64),
            repeat('f', 64), 'https://example.com/calendar', '{}'::jsonb,
            timestamptz '2026-07-19 00:00:00+00',
            timestamptz '2026-07-19 00:00:00+00',
            'FIRST_OBSERVED_AT_RETRIEVAL', 'CALENDAR_RESEARCH_ONLY',
            'RESEARCH_ONLY', array['PARTIAL_TIMESTAMPS']
        );
        raise exception 'PARTIAL_TIMESTAMPS_WERE_ACCEPTED';
    exception when check_violation then
        null;
    end;

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
            'TWSE', date '2026-07-20', true,
            timestamptz '2026-07-20 09:00:00+08',
            timestamptz '2026-07-20 13:30:00+08',
            timestamptz '2026-07-20 18:00:00+08',
            'SOURCE_ASSERTED', 'VERIFIED', fixture_source_id,
            'TEST', 'AVAILABLE_AFTER_CUTOFF', 'test', repeat('1', 64),
            repeat('2', 64), 'https://example.com/calendar', '{}'::jsonb,
            timestamptz '2026-07-20 18:01:00+08',
            timestamptz '2026-07-20 18:01:00+08', 'VERSIONED_SNAPSHOT',
            'POINT_IN_TIME_CALENDAR', 'PASS', '{}'::text[]
        );
        raise exception 'AVAILABLE_AFTER_CUTOFF_WAS_ACCEPTED';
    exception when check_violation then
        null;
    end;

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
            'TWSE', date '2026-07-20', false, null, null, null,
            'SOURCE_ASSERTED', 'VERIFIED', fixture_source_id,
            'TEST', 'CLOSED_DAY_OBSERVED_LATE', 'test', repeat('3', 64),
            repeat('4', 64), 'https://example.com/calendar', '{}'::jsonb,
            timestamptz '2026-07-21 00:00:00+08',
            timestamptz '2026-07-21 00:00:00+08', 'VERSIONED_SNAPSHOT',
            'POINT_IN_TIME_CALENDAR', 'PASS', '{}'::text[]
        );
        raise exception 'LATE_CLOSED_DAY_EVIDENCE_WAS_ACCEPTED';
    exception when check_violation then
        null;
    end;
end;
$validation$;

rollback;
