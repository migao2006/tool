begin;

set local search_path = pg_catalog, public, extensions;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

do $$
begin
  if exists (
    select 1
    from market_data.security_history
    where record_kind = 'CURRENT_DAILY_SNAPSHOT'
      and snapshot_date <> (available_at at time zone 'Asia/Taipei')::date
  ) then
    raise exception using
      errcode = 'check_violation',
      message = 'ROLLBACK_BLOCKED_LATE_SECURITY_SNAPSHOT_ROWS_EXIST';
  end if;
end;
$$;

alter table market_data.security_history
add constraint security_history_current_snapshot_check_rollback
check (
    (
        record_kind = 'CURRENT_DAILY_SNAPSHOT'
        and snapshot_date is not null
        and effective_from = snapshot_date
        and effective_to = snapshot_date + 1
        and (available_at at time zone 'Asia/Taipei')::date = snapshot_date
        and source_revision_hash is not null
    )
    or (
        record_kind = 'EFFECTIVE_INTERVAL'
        and snapshot_date is null
    )
) not valid;

alter table market_data.security_history
validate constraint security_history_current_snapshot_check_rollback;
alter table market_data.security_history
drop constraint security_history_current_snapshot_check;
alter table market_data.security_history
rename constraint security_history_current_snapshot_check_rollback
to security_history_current_snapshot_check;

commit;
