begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

alter table market_data.trading_calendar_observations
drop constraint trading_calendar_observations_session_check;

alter table market_data.trading_calendar_observations
add constraint trading_calendar_observations_session_check check (
    market in ('TWSE', 'TPEX')
    and calendar_verification_status in (
        'VERIFIED', 'UNRESOLVED', 'CONFLICT'
    )
    and market_basis in ('SOURCE_ASSERTED', 'SCHEDULING_HINT')
    and (
        (
            calendar_verification_status = 'VERIFIED'
            and (
                (
                    is_trading_day
                    and opens_at is not null
                    and closes_at is not null
                    and decision_data_cutoff_at is not null
                    and opens_at < closes_at
                    and closes_at <= decision_data_cutoff_at
                    and timezone('Asia/Taipei', opens_at)::date = trading_date
                    and timezone('Asia/Taipei', closes_at)::date = trading_date
                    and timezone(
                        'Asia/Taipei', decision_data_cutoff_at
                    )::date = trading_date
                )
                or (
                    not is_trading_day
                    and opens_at is null
                    and closes_at is null
                    and decision_data_cutoff_at is null
                )
            )
        )
        or (
            calendar_verification_status in ('UNRESOLVED', 'CONFLICT')
            and (
                (
                    is_trading_day
                    and (
                        (
                            opens_at is null
                            and closes_at is null
                            and decision_data_cutoff_at is null
                        )
                        or (
                            opens_at is not null
                            and closes_at is not null
                            and decision_data_cutoff_at is not null
                            and opens_at < closes_at
                            and closes_at <= decision_data_cutoff_at
                            and timezone(
                                'Asia/Taipei', opens_at
                            )::date = trading_date
                            and timezone(
                                'Asia/Taipei', closes_at
                            )::date = trading_date
                            and timezone(
                                'Asia/Taipei', decision_data_cutoff_at
                            )::date = trading_date
                        )
                    )
                )
                or (
                    not is_trading_day
                    and opens_at is null
                    and closes_at is null
                    and decision_data_cutoff_at is null
                )
            )
        )
    )
) not valid;

alter table market_data.trading_calendar_observations
validate constraint trading_calendar_observations_session_check;

alter table market_data.trading_calendar_observations
drop constraint trading_calendar_observations_status_check;

alter table market_data.trading_calendar_observations
add constraint trading_calendar_observations_status_check check (
    array_position(reason_codes, null) is null
    and (
        (
            calendar_verification_status = 'VERIFIED'
            and market_basis = 'SOURCE_ASSERTED'
            and available_at_basis in (
                'OFFICIAL_PUBLICATION_AT',
                'VERSIONED_SNAPSHOT'
            )
            and usage_scope = 'POINT_IN_TIME_CALENDAR'
            and system_status = 'PASS'
            and cardinality(reason_codes) = 0
            and (
                (
                    is_trading_day
                    and available_at <= decision_data_cutoff_at
                )
                or (
                    not is_trading_day
                    and timezone(
                        'Asia/Taipei', available_at
                    )::date <= trading_date
                )
            )
        )
        or (
            calendar_verification_status in ('UNRESOLVED', 'CONFLICT')
            and usage_scope = 'CALENDAR_RESEARCH_ONLY'
            and system_status in ('RESEARCH_ONLY', 'FAIL')
            and cardinality(reason_codes) > 0
        )
    )
) not valid;

alter table market_data.trading_calendar_observations
validate constraint trading_calendar_observations_status_check;

comment on constraint trading_calendar_observations_session_check
on market_data.trading_calendar_observations is
'VERIFIED sessions require complete times; unresolved date-only scheduling hints
may keep all session times null, but partial timestamp sets are rejected.';

commit;

notify pgrst, 'reload schema';
