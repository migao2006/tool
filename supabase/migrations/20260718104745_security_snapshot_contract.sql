begin;

alter table market_data.security_history
  add column if not exists record_kind text
    not null default 'EFFECTIVE_INTERVAL',
  add column if not exists snapshot_date date,
  add column if not exists source_revision_hash text;

alter table market_data.security_history
  alter column attention_flag drop default,
  alter column attention_flag drop not null,
  alter column disposal_flag drop default,
  alter column disposal_flag drop not null,
  alter column altered_trading_method_flag drop default,
  alter column altered_trading_method_flag drop not null,
  alter column full_cash_delivery_flag drop default,
  alter column full_cash_delivery_flag drop not null,
  alter column periodic_auction_flag drop default,
  alter column periodic_auction_flag drop not null,
  alter column suspended_flag drop default,
  alter column suspended_flag drop not null;

alter table market_data.security_history
  drop constraint if exists security_history_record_kind_check;
alter table market_data.security_history
  add constraint security_history_record_kind_check
  check (record_kind in ('EFFECTIVE_INTERVAL', 'CURRENT_DAILY_SNAPSHOT'));

alter table market_data.security_history
  drop constraint if exists security_history_trading_status_check;
alter table market_data.security_history
  add constraint security_history_trading_status_check
  check (trading_status in ('UNKNOWN', 'ACTIVE', 'SUSPENDED', 'STOPPED', 'DELISTED'));

alter table market_data.security_history
  drop constraint if exists security_history_source_revision_hash_check;
alter table market_data.security_history
  add constraint security_history_source_revision_hash_check
  check (
    source_revision_hash is null
    or source_revision_hash ~ '^[0-9a-f]{64}$'
  );

alter table market_data.security_history
  drop constraint if exists security_history_current_snapshot_check;
alter table market_data.security_history
  add constraint security_history_current_snapshot_check
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
  );

comment on column market_data.security_history.record_kind is
  'CURRENT_DAILY_SNAPSHOT is an observation on snapshot_date, not historical backfill.';
comment on column market_data.security_history.source_revision_hash is
  'SHA-256 of the deterministic composite source payload manifest.';
comment on column market_data.security_history.full_cash_delivery_flag is
  'True or false means observed; null means the connected source did not establish the state.';

commit;
