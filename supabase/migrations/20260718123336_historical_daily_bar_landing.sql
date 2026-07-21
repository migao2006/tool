begin;

set local search_path = pg_catalog, public, extensions;

create table if not exists market_data.historical_daily_bar_landing (
  landing_id bigint generated always as identity primary key,
  landing_key text not null unique,
  source_id bigint not null
    references market_data.data_sources(source_id),
  source_dataset text not null,
  source_version text not null,
  source_payload_hash text not null,
  source_revision_hash text not null,
  source_url text not null,
  source_row_index integer not null,
  source_row jsonb not null,
  source_symbol text,
  source_market_claim text,
  source_market_basis text not null,
  source_trade_date text,
  trade_date date,
  parse_status text not null,
  open_price numeric(20,6),
  high_price numeric(20,6),
  low_price numeric(20,6),
  close_price numeric(20,6),
  trading_volume numeric(24,4),
  trading_value numeric(24,4),
  trade_count bigint,
  first_observed_at timestamptz not null,
  available_at timestamptz not null,
  available_at_basis text not null,
  identity_resolution_status text not null,
  point_in_time_status text not null,
  usage_scope text not null,
  system_status text not null,
  reason_codes text[] not null,
  ingested_at timestamptz not null default now(),
  constraint historical_daily_bar_landing_provenance_check check (
    landing_key ~ '^[0-9a-f]{64}$'
    and nullif(btrim(source_dataset), '') is not null
    and nullif(btrim(source_version), '') is not null
    and source_payload_hash ~ '^[0-9a-f]{64}$'
    and source_revision_hash ~ '^[0-9a-f]{64}$'
    and source_url ~ '^https://'
    and source_row_index >= 0
    and available_at = first_observed_at
    and available_at_basis = 'FIRST_OBSERVED_AT_RETRIEVAL'
  ),
  constraint historical_daily_bar_landing_market_claim_check check (
    (
      source_market_claim is null
      and source_market_basis = 'UNAVAILABLE'
    )
    or (
      source_market_claim in ('TWSE', 'TPEX')
      and source_market_basis = 'SOURCE_ASSERTED'
    )
  ),
  constraint historical_daily_bar_landing_status_check check (
    parse_status in ('PARSED', 'QUARANTINED')
    and identity_resolution_status = 'UNRESOLVED'
    and point_in_time_status = 'UNVERIFIED'
    and usage_scope = 'RAW_LANDING_ONLY'
    and system_status = 'RESEARCH_ONLY'
    and cardinality(reason_codes) > 0
  ),
  constraint historical_daily_bar_landing_optional_source_values_check check (
    (
      source_symbol is null
      or (
        nullif(btrim(source_symbol), '') is not null
        and length(source_symbol) <= 32
      )
    )
    and (
      source_trade_date is null
      or (
        nullif(btrim(source_trade_date), '') is not null
        and length(source_trade_date) <= 64
      )
    )
  ),
  constraint historical_daily_bar_landing_parsed_values_check check (
    parse_status = 'QUARANTINED'
    or (
      source_symbol is not null
      and source_trade_date is not null
      and trade_date is not null
      and open_price is not null
      and high_price is not null
      and low_price is not null
      and close_price is not null
      and open_price > 0
      and high_price > 0
      and low_price > 0
      and close_price > 0
      and high_price >= greatest(open_price, low_price, close_price)
      and low_price <= least(open_price, high_price, close_price)
      and (trading_volume is null or trading_volume >= 0)
      and (trading_value is null or trading_value >= 0)
      and (trade_count is null or trade_count >= 0)
    )
  )
);

create unique index if not exists historical_daily_bar_landing_source_row_uidx
  on market_data.historical_daily_bar_landing (
    source_id,
    source_dataset,
    source_payload_hash,
    source_row_index
  );

create index if not exists historical_daily_bar_landing_identity_lookup_idx
  on market_data.historical_daily_bar_landing (
    source_symbol,
    trade_date
  )
  where parse_status = 'PARSED';

create index if not exists historical_daily_bar_landing_trade_date_idx
  on market_data.historical_daily_bar_landing (trade_date)
  where parse_status = 'PARSED';

create index if not exists historical_daily_bar_landing_available_at_idx
  on market_data.historical_daily_bar_landing (available_at);

create table if not exists market_data.historical_daily_bar_quarantine (
  quarantine_id bigint generated always as identity primary key,
  landing_key text not null
    references market_data.historical_daily_bar_landing(landing_key)
    on delete restrict,
  reason_code text not null,
  field_name text not null default '*',
  severity text not null default 'HARD_FAIL',
  issue_detail text,
  detected_at timestamptz not null default now(),
  constraint historical_daily_bar_quarantine_issue_check check (
    nullif(btrim(reason_code), '') is not null
    and length(reason_code) <= 128
    and nullif(btrim(field_name), '') is not null
    and length(field_name) <= 128
    and severity = 'HARD_FAIL'
    and (
      issue_detail is null
      or nullif(btrim(issue_detail), '') is not null
    )
  )
);

create unique index if not exists historical_daily_bar_quarantine_issue_uidx
  on market_data.historical_daily_bar_quarantine (
    landing_key,
    reason_code,
    field_name
  );

create index if not exists historical_daily_bar_quarantine_reason_idx
  on market_data.historical_daily_bar_quarantine (reason_code);

comment on table market_data.historical_daily_bar_landing is
  'Immutable raw historical daily-bar landing rows; never a formal security-master or training fact table.';
comment on column market_data.historical_daily_bar_landing.landing_key is
  'Deterministic SHA-256 key including source revision, used to make source-row ingestion idempotent.';
comment on column market_data.historical_daily_bar_landing.source_market_claim is
  'Nullable source claim only; it must not be inferred from the current security master.';
comment on column market_data.historical_daily_bar_landing.available_at is
  'Project first-retrieval time, not the historical exchange publication time.';
comment on column market_data.historical_daily_bar_landing.point_in_time_status is
  'UNVERIFIED until historical publication timing and immutable security identity are resolved.';
comment on table market_data.historical_daily_bar_quarantine is
  'One or more parse or contract issues linked to an immutable landing row.';

alter table market_data.historical_daily_bar_landing enable row level security;
alter table market_data.historical_daily_bar_quarantine enable row level security;

revoke all on market_data.historical_daily_bar_landing
  from public, anon, authenticated;
revoke all on market_data.historical_daily_bar_quarantine
  from public, anon, authenticated;
revoke all on sequence market_data.historical_daily_bar_landing_landing_id_seq
  from public, anon, authenticated;
revoke all on sequence market_data.historical_daily_bar_quarantine_quarantine_id_seq
  from public, anon, authenticated;

grant select, insert, update, delete
  on market_data.historical_daily_bar_landing to service_role;
grant select, insert, update, delete
  on market_data.historical_daily_bar_quarantine to service_role;
grant usage, select
  on sequence market_data.historical_daily_bar_landing_landing_id_seq
  to service_role;
grant usage, select
  on sequence market_data.historical_daily_bar_quarantine_quarantine_id_seq
  to service_role;

commit;

notify pgrst, 'reload schema';
