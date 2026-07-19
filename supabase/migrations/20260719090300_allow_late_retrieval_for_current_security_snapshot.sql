begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

alter table market_data.security_history
add constraint security_history_current_snapshot_check_v2
check (
    (
        record_kind = 'CURRENT_DAILY_SNAPSHOT'
        and snapshot_date is not null
        and effective_from = snapshot_date
        and effective_to = snapshot_date + 1
        and snapshot_date <= (available_at at time zone 'Asia/Taipei')::date
        and source_revision_hash is not null
    )
    or (
        record_kind = 'EFFECTIVE_INTERVAL'
        and snapshot_date is null
    )
) not valid;

alter table market_data.security_history
validate constraint security_history_current_snapshot_check_v2;
alter table market_data.security_history
drop constraint security_history_current_snapshot_check;
alter table market_data.security_history
rename constraint security_history_current_snapshot_check_v2
to security_history_current_snapshot_check;

comment on constraint security_history_current_snapshot_check
on market_data.security_history is
'Late retrieval is allowed after the source date; available_at stays actual.';

commit;

notify pgrst, 'reload schema';
